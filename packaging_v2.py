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
    def __init__(self, conf, comp):
        '''
        parse packaging.conf file and other init work

        @conf: location of config file
        @comp: choose from neutron, python-neutronclient and horizon
        '''
        self.comp = comp
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
            self.repo_dir = os.path.join(self.stack_dir, self.comp)
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
        for folder in (self.repo_dir, self.unpack_dir, self.staging_dir):
            if os.path.exists(folder):
                _runCmd('rm -rf %s' % folder, shell = True)        
        _mkdir(self.unpack_dir)
        _mkdir(self.staging_dir)
        _chdir(self.staging_dir)
        for subdir in 'RPMS SRPMS BUILD SOURCES SPECS tmp'.split():
            _mkdir(subdir)

    def clone_git_repo(self):
        '''
        clone upstream repository
        '''
        print_banner('clone %s' % self.remotes['origin'])
        _chdir(self.stack_dir)
        _runCmd('git clone %s' % self.remotes['origin'])

    def checkout_branch(self, branch, tag=None):
        '''
        checkout branch if tag is skipped 
        otherwise create a branch off from tag
        '''
        print_banner('checkout branch %s' % branch)
        _chdir(self.repo_dir)
        if tag:
            _runCmd('git checkout -b %s %s' % (branch, tag))
        else:
            _runCmd('git checkout %s' % branch)

    def pull_remotes(self):
        '''
        pull all remotes in self.remotes
        '''
        print_banner('pull remotes %s' % self.remotes)
        _chdir(self.repo_dir)
        output, rc = _runCmd('git remote -v')
        current_remotes = {}
        for line in output.split('\n'):
            if line:
                tokens = line.split()
                current_remotes[tokens[0]] = tokens[1]
        for remote in set(self.remotes) - set(current_remotes):
                _runCmd('git remote add %s %s' % (remote, self.remotes[remote]))
                _runCmd('git fetch %s' % remote)

    def cherry(self):
        '''
        generate the delta between upstream branch and cisco dev branch
        return: list of commit ids
        '''
        print_banner('generate the deltas between %s and %s' %
                     (self.upstream_branch, self.cisco_branch))
        _chdir(self.repo_dir)
        _runCmd('git checkout %s' % self.cisco_branch)
        output, rc = _runCmd('git cherry %s' % self.upstream_branch)
        deltas = [line[1:].strip() for line in output.split('\n')
                  if line.startswith('+')]
        return deltas

    def cherry_pick(self, deltas):
        '''
        cherry pick commits in deltas
        make sure on right branch when this function is called
        '''
        print_banner('cherry pick delta commits')
        _chdir(self.repo_dir)
        for commit in deltas:
            _runCmd('git cherry-pick %s' % commit, exit_on_error = False)

    def apply_redhat_patches(self):
        '''
        apply redhat patches in unpack_dir,
        make sure on right branch when this function is called
        '''
        print_banner('apply redhat patches in %s' % self.unpack_dir)
        _chdir(self.repo_dir)
        output, rc = _runCmd('ls %s' % os.path.join(self.unpack_dir, '*.patch'),
                             shell = True)
        for patch in sorted(output.split('\n')):
            if patch:
                while 'c' in _runCmd('git apply --ignore-whitespace %s' % patch,
                                     shell = True, check_result = True):
                    continue

    def download_rpm(self, rdo_location = None):
        '''
        download and unpack rpm if rdo_location is None,
        otherwise unpack the rdo package at rdo_location
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

    def rpmbuild(self, tarball):
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
            for line in f_old:
                if re.match(r'.*patch00.*', line, re.IGNORECASE):
                    f_new.write('#' + line)
                    continue
#            # removed for causing an error during build
#            elif line.find('neutron.egg-info/SOURCES.txt') != -1:
#                f_new.write('#'+line)
#                continue
                elif line.startswith('Source0:'):
                    tar_filename = line.split('/')[-1]
                    f_new.write('Source0:\t%s' % tar_filename)
                    continue
                else:
                    f_new.write(line)
        # copy over payload
        for filename in _listdir(self.unpack_dir):
            if (not fnmatch.fnmatch(filename, '*.spec') and
                not fnmatch.fnmatch(filename, '*.patch') and
                not fnmatch.fnmatch(filename, '*.tar.gz')):
                _rename(os.path.join(self.unpack_dir, filename),
                        os.path.join(self.staging_dir, 'SOURCES', filename))
        _rename(os.path.join(self.stack_dir, tarball),
                os.path.join(self.staging_dir, 'SOURCES', tarball))
        _rename(os.path.join(self.unpack_dir, 'tmp.spec'), 
                os.path.join(self.staging_dir, 'SPECS', self.spec_filename))
        # build
        _runCmd('rpmbuild --define "_topdir %s" -ba %s' %
                (self.staging_dir,
                 os.path.join(self.staging_dir, 'SPECS', self.spec_filename)),
                shell = True)

    def repackage(self, rdo = None):
        self.download_rpm(rdo)
        self.clone_git_repo()
        self.checkout_branch(self.upstream_branch, self.upstream_tag)
        self.pull_remotes()
        if self.comp != 'python-neutronclient':    
            self.checkout_branch(self.cisco_branch)
            deltas = self.cherry()
            if debug: pprint(deltas)        
            self.checkout_branch(self.upstream_branch)
        else:
            # for python-neutronclient, we only pick our commits to patch,
            # which is hard-coded here 
            deltas = ['7932447a633247408530c7baa99b055f52f7e882']
        self.apply_redhat_patches()
        self.cherry_pick(deltas)
        # create tar ball
        _chdir(self.stack_dir)
        # folder's name has to be %{rpmname}-%{rpmversion}
        # tarball's name has to be %{rpmname}-%{rpmversion}.tar.gz
        folder_name = self.comp + '-' + self.version
        tar_filename = folder_name + '.tar.gz'
        _rename(self.repo_dir, folder_name)
        _runCmd('tar -cvzf %s %s' % (tar_filename, folder_name))
        _rename(folder_name, self.repo_dir)
        self.rpmbuild(tar_filename)


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
    parser.add_argument('--rdo', help='location of rdo file')
    args = parser.parse_args()
    print args.comp, args.conf, args.rdo
    if 'neutron' == args.comp:
        neutron = Packaging(args.conf, 'neutron')
        neutron.repackage(args.rdo)
    if 'python-neutronclient' == args.comp:
        python_neutronclient = Packaging(args.conf, 'python-neutronclient')
        python_neutronclient.repackage(args.rdo)
