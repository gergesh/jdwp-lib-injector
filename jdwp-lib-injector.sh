#!/bin/bash
echo "[**] Android JDWP library injector by @ikoz"
if [ ! -f "$1" ]
  then
    echo "[!!] Please provide the path to a valid library SO file as the first argument"
    exit 1
fi
echo "[**] Pushing $1 to /data/local/tmp/"
adb push $1 /data/local/tmp/
F=/var/tmp/jdwpPidFile-$(date +%s)
echo "[**] Retrieving pid of running JDWP-enabled app"
adb jdwp > "$F" &
sleep 1
kill -9 $!
jdwp_pid=$(tail -1 "$F")
rm "$F"
echo "[**] JDWP pid is $F. Will forward tcp:8700 to jdwp:$jdwp_pid"
adb forward tcp:8700 jdwp:$jdwp_pid
echo "[**] Starting jdwp-shellifier.py to load library"
python jdwp-shellifier.py --target 127.0.0.1 --port 8700 --break-on android.app.Activity.onCreate --loadlib $1
echo "[**] Running frida-ps -U. If you see 'Gadget' then all worked fine!"
frida-ps -U
