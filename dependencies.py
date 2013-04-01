#!/usr/bin/env python3 -tt

# Copyright 2013 Jussi Pakkanen

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for external
# dependencies. Mostly just uses pkg-config but also contains
# custom logic for packages that don't provide them.

# Currently one file, should probably be split into a
# package before this gets too big.

import os, stat, glob, subprocess
from interpreter import InvalidArguments
from coredata import MesonException

class DependencyException(MesonException):
    def __init__(self, args, **kwargs):
        MesonException.__init__(args, kwargs)

class Dependency():
    def __init__(self):
        pass

    def get_compile_flags(self):
        return []

    def get_link_flags(self):
        return []

    def found(self):
        return False

    def get_sources(self):
        """Source files that need to be added to the target.
        As an example, gtest-all.cc when using GTest."""
        return []

class PackageDependency(Dependency): # Custom detector, not pkg-config.
    def __init__(self, dep):
        Dependency.__init__(self)
        self.dep = dep

    def get_link_flags(self):
        return self.dep.get_link_flags()

    def get_compile_flags(self):
        return self.dep.get_compile_flags()

    def found(self):
        return self.dep.found()

    def get_sources(self):
        return self.dep.get_sources()

# This should be an InterpreterObject. Fix it.

class PkgConfigDependency(Dependency):
    pkgconfig_found = False
    
    def __init__(self, name, required):
        Dependency.__init__(self)
        if not PkgConfigDependency.pkgconfig_found:
            self.check_pkgconfig()

        self.is_found = False
        p = subprocess.Popen(['pkg-config', '--modversion', name], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        out = p.communicate()[0]
        if p.returncode != 0:
            if required:
                raise DependencyException('Required dependency %s not found.' % name)
            self.modversion = 'none'
            self.cflags = []
            self.libs = []
        else:
            self.is_found = True
            self.modversion = out.decode().strip()
            p = subprocess.Popen(['pkg-config', '--cflags', name], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            out = p.communicate()[0]
            if p.returncode != 0:
                raise RuntimeError('Could not generate cflags for %s.' % name)
            self.cflags = out.decode().split()

            p = subprocess.Popen(['pkg-config', '--libs', name], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            out = p.communicate()[0]
            if p.returncode != 0:
                raise RuntimeError('Could not generate libs for %s.' % name)
            self.libs = out.decode().split()

    def get_modversion(self):
        return self.modversion

    def get_compile_flags(self):
        return self.cflags

    def get_link_flags(self):
        return self.libs

    def check_pkgconfig(self):
        p = subprocess.Popen(['pkg-config', '--version'], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        out = p.communicate()[0]
        if p.returncode != 0:
            raise RuntimeError('Pkg-config executable not found.')
        print('Found pkg-config version %s.' % out.decode().strip())
        PkgConfigDependency.pkgconfig_found = True

    def found(self):
        return self.is_found

class ExternalProgram():
    def __init__(self, name, fullpath=None):
        self.name = name
        self.fullpath = fullpath

    def found(self):
        return self.fullpath is not None

    def get_command(self):
        return self.fullpath

    def get_name(self):
        return self.name

class ExternalLibrary(Dependency):
    def __init__(self, name, fullpath=None):
        Dependency.__init__(self)
        self.name = name
        self.fullpath = fullpath

    def found(self):
        return self.fullpath is not None

    def get_name(self):
        return self.name
    
    def get_link_flags(self):
        if self.found():
            return [self.fullpath]
        return []

def find_external_dependency(name, kwargs):
    required = kwargs.get('required', False)
    if name in packages:
        dep = packages[name](kwargs)
        if required and not dep.found():
            raise DependencyException('Dependency "%s" not found' % name)
        return PackageDependency(dep)
    return PkgConfigDependency(name, required)

class BoostDependency():
    def __init__(self, kwargs):
        self.incdir = '/usr/include/boost'
        self.libdir = '/usr/lib'
        self.src_modules = {}
        self.lib_modules = {}
        self.detect_version()
        self.requested_modules = self.get_requested(kwargs)

        if self.version is not None:
            self.detect_src_modules()
            self.detect_lib_modules()
            self.validate_requested()
    
    def get_compile_flags(self):
        return []

    def get_requested(self, kwargs):
        modules = 'modules'
        if not modules in kwargs:
            raise InvalidArguments('Boost dependency must specify "%s" keyword.' % modules)
        candidates = kwargs[modules]
        if isinstance(candidates, str):
            return [candidates]
        for c in candidates:
            if not isinstance(c, str):
                raise InvalidArguments('Boost module argument is not a string.')
        return candidates

    def validate_requested(self):
        for m in self.requested_modules:
            if m not in self.src_modules:
                raise InvalidArguments('Requested Boost module "%s" not found.' % m)

    def found(self):
        return self.version is not None

    def get_version(self):
        return self.version

    def detect_version(self):
        ifile = open(os.path.join(self.incdir, 'version.hpp'))
        for line in ifile:
            if line.startswith("#define") and 'BOOST_LIB_VERSION' in line:
                ver = line.split()[-1]
                ver = ver[1:-1]
                self.version = ver.replace('_', '.')
                return
        self.version = None

    def detect_src_modules(self):
        for entry in os.listdir(self.incdir):
            entry = os.path.join(self.incdir, entry)
            if stat.S_ISDIR(os.stat(entry).st_mode):
                self.src_modules[os.path.split(entry)[-1]] = True

    def detect_lib_modules(self):
        globber = 'libboost_*.so' # FIXME, make platform independent.
        for entry in glob.glob(os.path.join(self.libdir, globber)):
            if entry.endswith('-mt.so'): # Fixme, seems to be Windows specific.
                continue
            lib = os.path.basename(entry)
            self.lib_modules[(lib.split('.')[0].split('_', 1)[-1])] = True

    def get_link_flags(self):
        flags = [] # Fixme, add -L if necessary.
        for module in self.requested_modules:
            if module in self.lib_modules:
                linkcmd = '-lboost_' + module
                flags.append(linkcmd)
        return flags

    def get_sources(self):
        return []

class GTestDependency():
    def __init__(self, kwargs):
        self.include_dir = '/usr/include'
        self.src_include_dir = '/usr/src/gtest'
        self.src_dir = '/usr/src/gtest/src'
        self.all_src = os.path.join(self.src_dir, 'gtest-all.cc')
        self.main_src = os.path.join(self.src_dir, 'gtest_main.cc')

    def found(self):
        return os.path.exists(self.all_src)
    def get_compile_flags(self):
        arr = []
        if self.include_dir != '/usr/include':
            arr.append('-I' + self.include_dir)
        arr.append('-I' + self.src_include_dir)
        return arr

    def get_link_flags(self):
        return ['-lpthread']
    def get_version(self):
        return '1.something_maybe'
    def get_sources(self):
        return [self.all_src, self.main_src]

class GMockDependency():
    def __init__(self, kwargs):
        self.libdir = '/usr/lib'
        self.libname = 'libgmock.so'

    def get_version(self):
        return '1.something_maybe'

    def get_compile_flags(self):
        return []

    def get_sources(self):
        return []

    def get_link_flags(self):
        return ['-lgmock']
    
    def found(self):
        fname = os.path.join(self.libdir, self.libname)
        return os.path.exists(fname)

class Qt5Dependency():
    def __init__(self, kwargs):
        self.root = '/usr'
        self.modules = []
        for module in kwargs.get('modules', []):
            self.modules.append(PkgConfigDependency('Qt5' + module))
        if len(self.modules) == 0:
            raise DependencyException('No Qt5 modules specified.')
        self.moc = ExternalProgram('moc')
        self.uic = ExternalProgram('uic')

    def get_version(self):
        return self.modules[0].get_version()

    def get_compile_flags(self):
        flags = []
        for m in self.modules:
            flags += m.get_compile_flags()
        return flags

    def get_sources(self):
        return []

    def get_link_flags(self):
        flags = []
        for module in self.modules:
            flags += module.get_link_flags()

    def found(self):
        if not self.moc.found():
            return False
        if not self.uic.found():
            return False
        for i in self.modules:
            if not i.found():
                return False
        return True

# This has to be at the end so the classes it references
# are defined.
packages = {'boost': BoostDependency,
            'gtest': GTestDependency,
            'gmock': GMockDependency,
            'qt5': Qt5Dependency,
            }
