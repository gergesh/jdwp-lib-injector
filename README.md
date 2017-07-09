# JDWP library injector script

## What is it ?
This script can be used to inject native shared libraries into debuggable Android applications.
It was mainly developed for injecting the Frida gadget library on non-rooted devices.

## How does it work?

The script can inject any library, however in this example we will be injecting Frida gadget.

1. Download the correct gadget for your architecture (arm/arm64/x86/x86_64) from https://github.com/frida/frida/releases/
2. On your device go to Developer options, "Select debug app" and select the desired application.
2. In the same screen, enable the "Wait for debugger" option
3. Start the application you want to inject the library into - this will pause waiting for a debugger to be connected.
4. On your shell, run `./jdwp-lib-injector.sh frida-gadget-10.1.5-android-arm64.so` or similar.

For more information, please visit https://koz.io/library-injection-for-debuggable-android-apps/

## Development
This script is based on [jdwp-shellifier](https://github.com/IOActive/jdwp-shellifier) by @\_hugsy\_, modified to facilitate library loading. The original README of jdwp-shellifier is at README-shellifier.md. Also included: a simple orchestration shell script to be used by end users. 
