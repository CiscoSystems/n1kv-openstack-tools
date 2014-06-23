'''
Author: Aaron Zhang (fenzhang)

Notes:
1. openstack-neutron.spec needs a bunch python libs as BuildRequires.
If they are missing, the rpm_build cmd will fail.
yum install them manually then once on the building server.
'''

import argparse
import ConfigParser
import fnmatch
import os
import re
import subprocess
import sys

from pprint import pprint
from ConfigParser import RawConfigParser as Parser

banner_fmt = '''
    *******************************************************
    * %s *
    *******************************************************
    '''
error_fmt = '''
    !!!!! %s !!!!!
    '''
debug = True


class Packaging(object):
    '''
    packaging class
    '''
    def __init__(self, conf, comp, timestamp = None):
        '''
        parse packaging.conf file and other init work

        @conf: location of config file
        @comp: choose from neutron, python-neutronclient and horizon
        '''
        self.comp = comp
        self.timestamp = timestamp
        try:
            config = Parser()
            config.read(conf)
            self.stack_dir = config.get('general', 'stack_dir')
            self.rpm_dir = config.get('general', 'rpm_dir')
            self.TOPDIR = config.get('general', 'TOPDIR') 
            self.rpm_pkg = config.get(comp, 'rpm_pkg')
            self.remotes = {'origin': config.get(comp, 'origin_remote'),
                            'cisco': config.get(comp, 'cisco_remote')}
            self.upstream_tag = config.get(comp, 'upstream_tag')
            self.upstream_branch = 'upstream-' + self.upstream_tag
            self.cisco_branch = config.get(comp, 'cisco_branch')
            self.patches_dir = os.path.join(self.stack_dir, 'patches')
            self.unpack_dir = os.path.join(self.rpm_dir,
                                           self.rpm_pkg.split('.')[0])
            self.staging_dir = os.path.join(self.TOPDIR, self.comp)
            self.spec_filename = self.rpm_pkg.split('.')[0] + '.spec'
        except ConfigParser.Error as e:
            print_error('error parsing config file %s' % conf)
            sys.exit(e)
        for folder in (self.stack_dir, self.rpm_dir, self.TOPDIR):
            if not os.path.exists(folder):
                _mkdir(folder)

    def clone_git_repo(self, stack, repo, pull_remotes = True):
        '''
        clone repository and pull remotes
        '''
        print_banner('clone %s in %s' % (self.remotes['origin'], stack))
        _chdir(stack)
        _runCmd('git clone %s' % self.remotes['origin'])
        if pull_remotes:
            self.pull_remotes(os.path.join(stack, repo))

    def pull_remotes(self, repo_dir):
        '''
        pull all remotes in self.remotes

        @repo_dir: absolute path to the repo
        '''
        print_banner('pull remotes %s in %s' % (self.remotes, repo_dir))
        _chdir(repo_dir)
        output, rc = _runCmd('git remote -v', shell = True)
        current_remotes = {}
        for line in output.split('\n'):
            if line:
                tokens = line.split()
                current_remotes[tokens[0]] = tokens[1]
        for remote in set(self.remotes) - set(current_remotes):
                _runCmd('git remote add %s %s' % (remote, self.remotes[remote]))
                _runCmd('git fetch %s' % remote)

    def check_up_to_date(self, repo_dir):
        '''
        check if current cisco branch is up-to-date

        @repo_dir: absolute path to the repo
        '''
        print_banner('check if code in %s is up-to-date' % repo_dir)
        _chdir(repo_dir)
        _runCmd('git checkout %s' % self.cisco_branch)
        output, rc = _runCmd('git pull')
        print output
        if 'Already up-to-date' in output:
            return True
        else:
            return False

    def create_cisco_patches(self, repo_dir):
        '''
        generate patches between cisco branch and upstream tag

        @repo_dir: absolute path to the repo
        '''
        print_banner('generate patches between %s and %s' %
                     (self.upstream_tag, self.cisco_branch))
        _chdir(repo_dir)
        _runCmd('git checkout %s' % self.cisco_branch)
        _runCmd('git format-patch -o %s %s' %
                (self.patches_dir, self.upstream_tag))
           
    def apply_patches(self, repo_dir, patches_dir, interact = False):
        '''
        apply patches on upstream branch,
        make sure on upstream branch before this function is called

        @repo_dir: absolute path to the repo on which patches will be applied
        @patches_dir: absolute path of the patches dir
        '''
        print_banner('apply patches in %s' % patches_dir)
        _chdir(repo_dir)
        output, rc = _runCmd('ls %s' % os.path.join(patches_dir, '*.patch'),
                             shell = True)
        for patch in sorted(output.split('\n')):
            if patch:
                if interact:
                    while 'r' in _runCmd(('git apply --ignore-whitespace %s' %
                                          patch),
                                         shell = True, check_result = True):
                        continue
                else:
                    _runCmd('git apply --ignore-whitespace %s' % patch,
                            shell = True, exit_on_error = False)

    def download_rpm(self, rdo_location = None):
        '''
        download and unpack rpm if rdo_location is None,
        otherwise unpack the rdo package at rdo_location

        @rdo_location: absolute path to the rdo package
        '''
        print_banner('download and unpack %s into %s' %
                     (self.rpm_pkg, self.unpack_dir))
        _chdir(self.unpack_dir)
        if not rdo_location:
            _runCmd('yumdownloader --source %s' % self.rpm_pkg)
        else:
            _runCmd('cp %s .' % rdo_location, shell = True)
        filename = _listdir('.')[0]
        _runCmd('rpm2cpio %s | cpio -idmv' % filename, shell = True)
        output, rc = _runCmd('ls *.src.rpm', shell = True)
        # %{self.rpm_pkg}-%{version}-%{release}.src.rpm
        # e.g. openstack-neuron-2014.1-19.el6ost.src.rpm 
        src_rpm = output.split('\n')[0]
        version_release = (src_rpm.replace(self.rpm_pkg.split('.')[0] + '-', '')
                           .replace('.src.rpm', ''))
        self.version, self.release = version_release.split('-')
        print 'version: %s, release %s' % (self.version, self.release)

    def rpmbuild(self):
        '''
        update spec file,
        create TOPDIR,
        copy over sources and spec,
        then build rpm
        '''
        print_banner('build rpm')
        _chdir(self.unpack_dir)
        with open(self.spec_filename, 'r') as f_old, \
             open('tmp.spec', 'w') as f_new:
            f_new.write('# building timestamp:\t%s\n' % self.timestamp)
            for line in f_old:
                if re.match(r'.*patch00.*', line, re.IGNORECASE):
                    f_new.write('#' + line)
                    continue
                elif line.startswith('Source0:'):
                    tar_filename = line.split('/')[-1]
                    f_new.write('Source0:\t%s' % tar_filename)
                    continue
                else:
                    f_new.write(line)
        # copy over payload
        for filename in _listdir('.'):
            if (not fnmatch.fnmatch(filename, '*.spec') and
                not fnmatch.fnmatch(filename, '*.patch')):
                _rename(filename,
                        os.path.join(self.staging_dir, 'SOURCES', filename))
        _rename('tmp.spec',
                os.path.join(self.staging_dir, 'SPECS', self.spec_filename))
        # build
        _runCmd('rpmbuild --define "_topdir %s" -ba %s' %
                (self.staging_dir,
                 os.path.join(self.staging_dir, 'SPECS', self.spec_filename)),
                shell = True)

    def repackage(self, rdo = None, force = False):
        '''
        main logic
        
        @return if there is no change since last time repackage,
                skip package and return 0, otherwise return 1
        '''
        if os.path.exists(os.path.join(self.stack_dir, self.comp)):
            _chdir(os.path.join(self.stack_dir, self.comp))
            up_to_date = self.check_up_to_date(os.path.join(self.stack_dir,
                                                            self.comp))
            if not force and up_to_date:
                print '!!! SKIPPING %s PACKAGE ALREADY UPDATED !!!' % self.comp
                return 0
        else:
            self.clone_git_repo(self.stack_dir, self.comp)
        # clean up workspace
        for folder in (self.patches_dir, self.unpack_dir, self.staging_dir):
            if os.path.exists(folder):
                _runCmd('rm -rf %s' % folder, shell = True)        
            _mkdir(folder)
        _chdir(self.staging_dir)
        for subdir in 'RPMS SRPMS BUILD SOURCES SPECS tmp'.split():
            _mkdir(subdir)

        self.create_cisco_patches(os.path.join(self.stack_dir, self.comp))
        self.download_rpm(rdo)
        self.clone_git_repo(self.unpack_dir, self.comp, pull_remotes = False)
        source_dir = os.path.join(self.unpack_dir, self.comp)
        _chdir(source_dir)
        _runCmd('git checkout -b %s %s' %
                (self.upstream_branch, self.upstream_tag))
        self.apply_patches(source_dir, self.unpack_dir)
        self.apply_patches(source_dir, self.patches_dir)
        '''
        create tar ball
        folder's name has to be %{rpmname}-%{rpmversion}
        tarball's name has to be %{rpmname}-%{rpmversion}.tar.gz
        '''
        _chdir(self.unpack_dir)
        folder_name = self.comp + '-' + self.version
        tarball_name = folder_name + '.tar.gz'
        _rename(self.comp, folder_name)
        _runCmd('tar -cvzf %s %s' % (tarball_name, folder_name))
        self.rpmbuild()
        return 1


def _chdir(path):
    print '# cd %s' % path
    os.chdir(path)


def _mkdir(path, mode = 0777):
    print '# mkdir %s' % path
    os.mkdir(path)


def _listdir(path):
    print '# ls %s' % path
    return os.listdir(path)


def _rename(srcpath, dstpath):
    print '# mv %s %s' % (srcpath, dstpath)
    os.rename(srcpath, dstpath)

def _runCmd(cmd, stderr = None, shell = False, echo_cmd = True,
            check_result = False, exit_on_error = True):
    if echo_cmd:
        print '#', cmd
    cmd_args = cmd if shell else cmd.split()
    rc = 0
    try:
        output = subprocess.check_output(cmd_args,
                                         stderr = stderr,
                                         shell = shell)
    except subprocess.CalledProcessError as e:
        if check_result:
            print_error(e)
            resume = ''
            while resume not in ('r', 'n'):
                resume = raw_input('press "r" to retry or '
                                   '"n" to next operation: ')
            return resume, e.returncode 
        else:
            if exit_on_error:
                sys.exit(e.returncode)
            else: 
                return e, e.returncode
    return output, rc


def print_date():
    output, rc = _runCmd('date --utc', echo_cmd = False)
    print output


def print_banner(msg):
    print banner_fmt % msg
    print_date()


def print_error(err):
    print error_fmt % err


if __name__ == '__main__':
    print sys.argv
    parser = argparse.ArgumentParser()
    parser.add_argument('comp')
    parser.add_argument('--conf', help='location of packaging.conf file')
    parser.add_argument('--rdo', help='absolute path of rdo file')
    parser.add_argument(
           '--force',
           help = 'force to recreate package no matter if cisco code is changed',
           action = 'store_true')
    args = parser.parse_args()
    print args.comp, args.conf, args.rdo
    if 'neutron' == args.comp:
        neutron = Packaging(args.conf, 'neutron')
        neutron.repackage(args.rdo, args.force)
    if 'python-neutronclient' == args.comp:
        python_neutronclient = Packaging(args.conf, 'python-neutronclient')
        python_neutronclient.repackage(args.rdo, args.force)
