"""CI 与本地的探针入库清单不许各写各的。

daily.yml 的 `store.py --ingest-probes` 是一份手抄清单，run_all.py 的 7a 是另一份。
两份一旦漂移，CI 就会静默少消费某一路判定（5f py_probe 合入 main 当天就踩了：
探针产物进了仓、入库清单里没有它，等于白测）。这里把两份清单钉成必须相等。
"""
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

YML = os.path.join(_ROOT, ".github", "workflows", "daily.yml")
PROBE_RE = re.compile(r"probe/[A-Za-z0-9_]+\.json")


def from_daily_yml(text):
    """取 store.py 那一步 --ingest-probes 后面、命令结束前的探针文件。

    注释里也会写 "--ingest-probes"（说明 CI 只消费不重跑），所以要扫所有出现处，
    取第一个真带探针文件列表的窗口——只看第一处会解析出空表，让守护空转。
    """
    for m in re.finditer(r"--ingest-probes", text):
        tail = text[m.end():]
        end = len(tail)
        for stop in ("|| true", "\n\n"):
            j = tail.find(stop)
            if j >= 0:
                end = min(end, j)
        hits = sorted(set(PROBE_RE.findall(tail[:end])))
        if hits:
            return hits
    return []


def from_run_all():
    import run_all
    for stage_id, _desc, argv, _required, _env in run_all.STAGES:
        if stage_id == "7a":
            return sorted({a for a in argv if PROBE_RE.fullmatch(a)})
    raise AssertionError("run_all.py 里找不到 7a 阶段")


class ProbeIngestListTest(unittest.TestCase):
    def test_ci_list_is_not_empty_and_parsed(self):
        with open(YML, encoding="utf-8") as f:
            ci = from_daily_yml(f.read())
        # 解析器若失配会返回空表，两个空表相等同样能"通过"——先钉住它真的取到了东西
        self.assertGreaterEqual(len(ci), 5, "daily.yml 探针清单没解析出来，守护本身失效了")
        self.assertIn("probe/sites_probe.json", ci)

    def test_ci_and_local_lists_match(self):
        with open(YML, encoding="utf-8") as f:
            ci = from_daily_yml(f.read())
        local = from_run_all()
        self.assertEqual(
            ci, local,
            "daily.yml 与 run_all.py 7a 的 --ingest-probes 清单漂移了：CI 会静默少消费判定")

    def test_every_ingested_probe_file_exists(self):
        with open(YML, encoding="utf-8") as f:
            ci = from_daily_yml(f.read())
        missing = [p for p in ci if not os.path.isfile(os.path.join(_ROOT, p))]
        self.assertEqual(missing, [], "入库清单引用了仓内不存在的探针产物")

    def test_parser_stops_at_command_end(self):
        # 下一条命令里的 probe 路径不能被吞进本步清单
        text = ("run: |\n  python scripts/store.py --ingest-probes probe/a.json probe/b.json "
                "|| true\n\n  - name: next\n    run: python x.py probe/zzz.json\n")
        self.assertEqual(from_daily_yml(text), ["probe/a.json", "probe/b.json"])


if __name__ == "__main__":
    unittest.main()
