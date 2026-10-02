import dalvik.system.DexClassLoader;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.FileWriter;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/**
 * csp 真机五关探针 v2（app_process 直跑，CLASSPATH 里必须挂宿主 apk 提供 catvod 接口）。
 *
 * usage:
 *   CLASSPATH=/data/local/tmp/runner2.jar:/data/app/.../base.apk \
 *   app_process / Main2 jobs.json out.jsonl
 * jobs.json: [{"id","cls","jar","cfg"}]   cfg=站点 ext 初始化参数（可空）
 *
 * 与 v1 的差别（v1 全 C0 的两个根因）：
 *  1) spider 类 implements com.github.catvod.crawler.Spider，该接口由宿主 apk 提供；
 *     classpath 里没有它时 ART 报的是 ClassNotFoundException（不是 NoClassDefFoundError），
 *     所以必须把宿主 apk 挂进 CLASSPATH。
 *  2) 各家 jar 的接口签名不同（homeContent(boolean) vs (boolean,String) 等），
 *     所以这里不写死签名：按方法名找、按形参类型现场造实参。
 * 等级 = 通过关卡数（首页/分类/搜索/详情/播放）→ C0..C5，与产物里 9-28 真机口径一致。
 */
public class Main2 {
    static final String[] PKGS = {
        "", "com.github.catvod.spider.", "com.spider.", "com.github.catvod.jar.",
        "com.okxjar.", "io.github.", "com.fongmi.android.tv.api.init."
    };
    static final int CALL_MS = 20000;
    static final String KW = "庆余年";
    static Object ctx;
    static ClassLoader parent = Main2.class.getClassLoader();

    public static void main(String[] args) throws Exception {
        if (args.length < 2) { System.out.println("need jobs out"); return; }
        String host = args.length > 2 ? args[2] : System.getenv("CSP_HOST_PKG");
        ctx = (host == null || host.length() == 0) ? systemContext() : hostContext(host);
        System.out.println("MODE host=" + host + " ctx=" + (ctx == null ? "NULL" : ctx.getClass().getName()));
        if (ctx != null) {
            Object l = ctx.getClass().getMethod("getClassLoader").invoke(ctx);
            if (l instanceof ClassLoader) {
                parent = (ClassLoader) l;
                System.out.println("loader=" + parent.getClass().getName());
            }
        }
        JSONArray jobs = new JSONArray(slurp(args[0]));
        FileWriter out = new FileWriter(args[1]);
        ExecutorService ex = Executors.newSingleThreadExecutor();
        ExecutorService guard = Executors.newCachedThreadPool();
        for (int i = 0; i < jobs.length(); i++) {
            final JSONObject j = jobs.getJSONObject(i);
            JSONObject r;
            // 看门狗：gate 有 20s 超时，但构造函数与宿主 Init.init 里的阻塞 DNS/HTTP
            // 不受控——一个 jar 卡住就整块挂死（实测 15 分钟不出下一行）。
            try {
                r = guard.submit(new Callable<JSONObject>() {
                    public JSONObject call() { return probe(ex, j); }
                }).get(120, TimeUnit.SECONDS);
            } catch (Throwable t) {
                r = new JSONObject();
                put(r, "id", j.optString("id"));
                put(r, "level", "C?");
                put(r, "err", "watchdog120s:" + root(t));
                put(r, "gates", "0");
            }
            out.write(r.toString() + "\n");
            out.flush();
            System.out.println("[" + (i + 1) + "/" + jobs.length() + "] " + j.optString("id")
                    + " -> " + r.optString("level") + " " + clip(r.optString("err", ""), 90));
        }
        out.close();
        ex.shutdownNow();
        guard.shutdownNow();
        System.exit(0);
    }

    static Object systemContext() {
        try {
            Class.forName("android.os.Looper").getMethod("prepareMainLooper").invoke(null);
            Class<?> at = Class.forName("android.app.ActivityThread");
            Object thread = at.getMethod("systemMain").invoke(null);
            return at.getMethod("getSystemContext").invoke(thread);
        } catch (Throwable t) {
            System.out.println("systemMain/getSystemContext 失败: " + t.getClass().getSimpleName()
                    + ":" + root(t));
            return null;
        }
    }

    /** 逐个 init 重载试：(Context,String) / (Context,List) / (Context) 各家壳要的不一样。 */
    static String tryHostInit(Method im, Object ctx, String seed, String url) {
        try {
            Class<?>[] pts = im.getParameterTypes();
            if (pts.length == 1) { im.invoke(null, ctx); }
            else if (pts.length == 2 && pts[1] == String.class) { im.invoke(null, ctx, seed); }
            else if (pts.length == 2 && java.util.List.class.isAssignableFrom(pts[1])) {
                java.util.ArrayList<String> l = new java.util.ArrayList<String>();
                l.add(seed);
                im.invoke(null, ctx, l);
            } else {
                Object[] a = new Object[pts.length];
                a[0] = ctx;
                for (int i = 1; i < pts.length; i++)
                    a[i] = pts[i] == int.class ? Integer.valueOf(0) : null;
                im.invoke(null, a);
            }
            return im.getName() + "/" + im.getParameterTypes().length + (seed.equals(url) ? "url" : "path");
        } catch (Throwable t) { return null; }
    }

    /** CONTEXT_INCLUDE_CODE(1) | CONTEXT_IGNORE_SECURITY(2)：拿宿主 apk 的类与真 Context。 */
    static Object hostContext(String pkg) {
        try {
            Object sys = systemContext();
            if (sys == null) return null;
            Method cpc = sys.getClass().getMethod("createPackageContext", String.class, int.class);
            Object app = cpc.invoke(sys, pkg, 1 | 2);
            Method gac = app.getClass().getMethod("getApplicationContext");
            Object real = gac.invoke(app);
            return real != null ? real : app;
        } catch (Throwable t) {
            System.out.println("createPackageContext(" + pkg + ") 失败: " + t.getClass().getSimpleName()
                    + ":" + root(t) + "，退回 system Context");
            return null;
        }
    }

    static String slurp(String p) throws Exception {
        BufferedReader br = new BufferedReader(new FileReader(p));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        br.close();
        return sb.toString();
    }

    static JSONObject probe(ExecutorService ex, JSONObject j) {
        JSONObject r = new JSONObject();
        put(r, "id", j.optString("id"));
        long t0 = System.currentTimeMillis();
        String jar = j.optString("jar"), cls = j.optString("cls");
        try {
            DexClassLoader dl = new DexClassLoader(jar, "/data/local/tmp/dexopt", null, parent);
            Class<?> sp = null;
            String loadErr = "";
            for (String p : PKGS) {
                try { sp = dl.loadClass(p + cls); break; }
                catch (Throwable t) { loadErr += p + cls + ":" + t.getClass().getSimpleName() + ";"; }
            }
            if (sp == null) { put(r, "level", "C0"); put(r, "err", clip(loadErr, 260)); return finish(r, t0); }
            gerr = "";
            Object inst;
            try {
                Constructor<?> c = sp.getDeclaredConstructor();
                c.setAccessible(true);
                inst = c.newInstance();
            } catch (Throwable t) {
                put(r, "level", "C0"); put(r, "err", "ctor:" + root(t)); return finish(r, t0);
            }
            String err = "";
            // TVBox 加载 jar 的先决步骤：Init.init(context, jarPath)——缺它很多 spider 直接 NPE
            String[] inits = {"com.github.catvod.spider.Init", "com.github.catvod.crawler.Init",
                              "com.github.catvod.jar.Init"};
            String url = j.optString("url", "");
            String[] seeds = url.length() > 0 ? new String[]{url, jar} : new String[]{jar};
            for (String in : inits) {
                Class<?> ic;
                try { ic = dl.loadClass(in); } catch (Throwable t) { continue; }
                java.util.ArrayList<Method> cands = new java.util.ArrayList<Method>();
                for (Method im : ic.getDeclaredMethods()) {
                    if (im.getName().equals("init") && !java.lang.reflect.Modifier.isStatic(im.getModifiers()) == false) { }
                    if (im.getName().equals("init")) { im.setAccessible(true); cands.add(im); }
                }
                java.util.Collections.sort(cands, new java.util.Comparator<Method>() {
                    public int compare(Method a, Method b) {
                        return rank(a) - rank(b);          // 先 (Context,String)，再 (Context,List)，最后 (Context)
                    }
                    int rank(Method m) {
                        Class<?>[] p = m.getParameterTypes();
                        if (p.length != 2) return 3;
                        if (p[1] == String.class) return 1;
                        if (java.util.List.class.isAssignableFrom(p[1])) return 2;
                        return 4;
                    }
                });
                for (Method im : cands) {
                    for (String seed : seeds) {
                        String how = tryHostInit(im, ctx, seed, url);
                        if (how != null) { err += "hostInit=" + in + "." + how + ":ok;"; break; }
                    }
                }
            }
            try {
                Method ini = sp.getMethod("init", android.content.Context.class, String.class);
                ini.invoke(inst, ctx, j.optString("cfg", ""));
            } catch (Throwable t) { err += "init:" + root(t) + ";"; }
            String home = gate(ex, inst, "homeContent");
            String tid = firstClassId(home);
            String cat = gate(ex, inst, "categoryContent", tid == null ? "1" : tid, "");
            String search = gate(ex, inst, "searchContent", KW);
            // 详情/播放要用真实 id/url 串起来，不然拿到的都是假通过
            String vid = firstNonEmpty(firstId(search), firstId(cat), firstId(home));
            String detail = vid == null ? null : gate(ex, inst, "detailContent", vid);
            String purl = playUrl(detail);
            String play = purl == null ? null : gate(ex, inst, "playerContent", "", purl);
            boolean h = looks(home, "list", "class"), c = looks(cat, "list");
            boolean s = listLen(search) > 0, d = looks(detail, "list");
            boolean p = playable(play);
            int n = (h ? 1 : 0) + (c ? 1 : 0) + (s ? 1 : 0) + (d ? 1 : 0) + (p ? 1 : 0);
            r.put("home", h); r.put("cat", c); r.put("search", s);
            r.put("detail", d); r.put("play", p);
            r.put("catCount", listLen(cat)); r.put("searchHit", listLen(search));
            put(r, "level", "G" + n);
            put(r, "gates", String.valueOf(n));
            put(r, "gateErr", clip(gerr, 260));
            if (n == 0) {
                // 关卡全没过但不一定抛异常：也可能是返回了内容却不像列表。
                // 不记返回形态就只能干猜「站点真空」还是「looks() 判据太窄」
                // （本轮 734 个 G0 里 261 个连 gateErr 都是空的，正是这一类）。
                put(r, "homeLen", String.valueOf(home == null ? -1 : home.length()));
                put(r, "homeHead", clip(home, 140));
                put(r, "catLen", String.valueOf(cat == null ? -1 : cat.length()));
            }
            if (!err.isEmpty()) put(r, "err", clip(err, 200));
        } catch (Throwable t) {
            put(r, "level", "C?"); put(r, "err", clip("" + root(t), 260));
        }
        return finish(r, t0);
    }

    /** 按方法名找重载，形参按类型现场填值；返回字符串化结果，失败返回 null。 */
    static String gerr = "";

    static String gate(ExecutorService ex, final Object inst, final String name, final String... hints) {
        Method m = pick(inst.getClass(), name);
        if (m == null) { gerr += name + ":NoSuchMethod;"; return null; }
        final Object[] argv = fill(m.getParameterTypes(), hints);
        Future<String> f = ex.submit(new Callable<String>() {
            public String call() throws Exception {
                Object v = m.invoke(inst, argv);
                return v == null ? null : String.valueOf(v);
            }
        });
        try { return f.get(CALL_MS, TimeUnit.MILLISECONDS); }
        catch (Throwable t) { f.cancel(true); gerr += name + ":" + root(t) + ";"; return null; }
    }

    static Method pick(Class<?> k, String name) {
        Method best = null;
        for (Class<?> c = k; c != null && c != Object.class; c = c.getSuperclass()) {
            for (Method m : c.getDeclaredMethods()) {
                if (!m.getName().equals(name) || java.lang.reflect.Modifier.isStatic(m.getModifiers())) continue;
                m.setAccessible(true);
                if (best == null || m.getParameterTypes().length < best.getParameterTypes().length) best = m;
            }
        }
        if (best == null) {
            for (Method m : k.getMethods()) if (m.getName().equals(name)) { best = m; break; }
        }
        return best;
    }

    static Object[] fill(Class<?>[] pts, String[] hints) {
        Object[] a = new Object[pts.length];
        int hi = 0;
        for (int i = 0; i < pts.length; i++) {
            Class<?> t = pts[i];
            if (t == boolean.class || t == Boolean.class) a[i] = Boolean.FALSE;
            else if (t == int.class || t == Integer.class) a[i] = Integer.valueOf(hi < hints.length ? hints[hi++] : "1");
            else if (t == long.class || t == Long.class) a[i] = Long.valueOf(0);
            else if (t == String.class) a[i] = hi < hints.length ? hints[hi++] : "";
            else if (java.util.Map.class.isAssignableFrom(t)) a[i] = new HashMap<String, String>();
            else if (java.util.List.class.isAssignableFrom(t)) a[i] = new ArrayList<String>();
            else a[i] = null;
        }
        return a;
    }

    /** homeContent 的 tab 列表：class[].type_id / typeId / id，分类要用真 tid。 */
    static String firstClassId(String json) {
        if (json == null) return null;
        try {
            JSONObject o = new JSONObject(json);
            JSONArray a = o.optJSONArray("class");
            if (a == null) a = o.optJSONArray("list");
            if (a == null || a.length() == 0) return null;
            JSONObject c = a.optJSONObject(0);
            String[] keys = {"type_id", "typeId", "id", "t"};
            for (String k : keys) {
                String v = c.optString(k, "");
                if (v.length() > 0) { int d = v.indexOf(36); return d > 0 ? v.substring(0, d) : v; }
            }
        } catch (Exception ignored) { }
        return null;
    }

    static String firstId(String json) {
        if (json == null) return null;
        try {
            JSONArray a = new JSONObject(json).optJSONArray("list");
            if (a == null) return null;
            for (int i = 0; i < a.length(); i++) {
                String id = a.optJSONObject(i).optString("id", "");
                if (id.length() > 0) {
                    int k = id.indexOf("$$$");
                    return k > 0 ? id.substring(0, k) : id;
                }
            }
        } catch (Exception ignored) { }
        return null;
    }

    /** vod_play_url 形如 源名$$$url1$$$url2#url3；取第一个 http 开头的地址。 */
    static String playUrl(String json) {
        if (json == null) return null;
        try {
            JSONArray a = new JSONObject(json).optJSONArray("list");
            if (a == null || a.length() == 0) return null;
            String u = a.optJSONObject(0).optString("vod_play_url", "");
            String[] parts = u.split("[$$$\n#]");
            for (String seg : parts) {
                int i = seg.indexOf("http");
                if (i >= 0) return seg.substring(i);
            }
        } catch (Exception ignored) { }
        return null;
    }

    static boolean playable(String json) {
        if (json == null) return false;
        try {
            JSONObject o = new JSONObject(json);
            String u = o.optString("url", "");
            if (u.startsWith("http") || u.contains(".m3u8") || u.contains("/")) return u.length() > 8;
            return o.has("parse") || o.optString("playUrl", "").length() > 8;
        } catch (Exception e) {
            return false;
        }
    }

    static String firstNonEmpty(String... vs) {
        for (String v : vs) if (v != null && v.length() > 0) return v;
        return null;
    }

    static boolean looks(String s, String... needles) {
        if (s == null) return false;
        for (String n : needles) if (s.contains(n)) return true;
        return false;
    }

    static int listLen(String s) {
        if (s == null) return 0;
        try {
            JSONArray a = new JSONObject(s).optJSONArray("list");
            return a == null ? 0 : a.length();
        } catch (Exception e) { return 0; }
    }

    static JSONObject finish(JSONObject r, long t0) {
        try { r.put("ms", System.currentTimeMillis() - t0); } catch (Exception ignored) { }
        try { r.put("evidence", "app-process-five-gate"); } catch (Exception ignored) { }
        return r;
    }

    static String root(Throwable t) {
        while (t.getCause() != null && t.getCause() != t) t = t.getCause();
        String m = t.getClass().getSimpleName() + ":" + t.getMessage();
        return m.length() > 160 ? m.substring(0, 160) : m;
    }

    static String clip(String s, int n) {
        if (s == null) return "";
        return s.length() > n ? s.substring(0, n) : s;
    }

    static void put(JSONObject o, String k, String v) {
        try { o.put(k, v == null ? "" : v); } catch (Exception ignored) { }
    }
}
