#!/bin/bash
# 构建真机工装 jar：javac(android bootcp) -> java 直调 D8 -> jar cf
# usage: build_jar.sh <Main.java|Diag.java|Diag2.java> <out.jar> [额外依赖 jar...]
set -e
cd "$(dirname "$0")"
SDK=${SDK:-${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}}
BT=$SDK/build-tools/34.0.0
AJ=$SDK/platforms/android-34/android.jar
SRC=$1; OUT=$2; shift 2
BASE=$(basename "$SRC" .java)
rm -rf "bc_$BASE" "bo_$BASE"
mkdir -p "bc_$BASE" "bo_$BASE"
javac -encoding UTF-8 -source 8 -target 8 -nowarn -bootclasspath "$AJ" -d "bc_$BASE" "$SRC"
CLS=""
for c in $(find "bc_$BASE" -name "*.class"); do CLS="$CLS $(cygpath -w "$c")"; done
ARGS=""
for j in "$@"; do ARGS="$ARGS $(cygpath -w "$j")"; done
java -cp "$(cygpath -w "$BT/lib/d8.jar")" com.android.tools.r8.D8 --release --min-api 21 \
  --lib "$(cygpath -w "$AJ")" --classpath "$(cygpath -w "$AJ")" \
  --output "$(cygpath -w "bo_$BASE")" $CLS $ARGS
(cd "bo_$BASE" && jar cf "../$OUT" classes*.dex)
echo "BUILD OK $OUT $(stat -c%s "$OUT") bytes"
