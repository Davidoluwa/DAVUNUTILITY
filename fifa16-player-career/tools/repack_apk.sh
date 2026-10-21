#!/bin/sh
# Puts a new libpv.so into the signed app and signs it again with the same key (v1 + v2, as the original), so it
# installs over the current one and keeps the game's data, saves and OBB.
# usage: sh tools/repack_apk.sh <original.apk> <libpv.so> <out.apk> <keystore.jks> <alias> <password file> <build-tools dir> [key password file]
#   the key password file only when the key's password differs from the keystore's
#   build-tools dir: an Android build-tools folder with zipalign and lib/apksigner.jar (e.g. build-tools_r34 "android-14")
set -eu
IN=$1; LIB=$2; OUT=$3; KS=$4; ALIAS=$5; PASS=$6; BT=$7; KEYPASS=${8:-}
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
cp "$IN" "$W/u.apk"
# the old JAR signature goes (apksigner writes a new one); the lib is replaced stored, as every lib in the app is
zip -q -d "$W/u.apk" 'META-INF/CERT.SF' 'META-INF/CERT.RSA' 'META-INF/MANIFEST.MF'
mkdir -p "$W/x/lib/armeabi-v7a"
cp "$LIB" "$W/x/lib/armeabi-v7a/libpv.so"
(cd "$W/x" && zip -q -0 -X "$W/u.apk" lib/armeabi-v7a/libpv.so)
# stored entries on 4 bytes, .so on 4 KiB pages (the loader maps them straight from the APK)
"$BT/zipalign" -p -f 4 "$W/u.apk" "$W/a.apk"
# (apksigner reads --ks-pass and --key-pass naming one file as two lines of it: the key password is given only when it
# has a file of its own; without it apksigner tries the keystore's)
set -- --ks "$KS" --ks-key-alias "$ALIAS" --ks-pass "file:$PASS"
if [ -n "$KEYPASS" ]; then set -- "$@" --key-pass "file:$KEYPASS"; fi
java -jar "$BT/lib/apksigner.jar" sign "$@" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled false --v4-signing-enabled false \
  --out "$OUT" "$W/a.apk"
"$BT/zipalign" -c -p 4 "$OUT"
java -jar "$BT/lib/apksigner.jar" verify -v --print-certs "$OUT" | grep -E "^Verif|certificate SHA-256"
