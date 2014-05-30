#! /opt/rh/python27/root/usr/bin/python

import argparse
import os
import sys
import re
import subprocess
import fnmatch
from pprint import pprint

neutron_remotes = {'origin': 'https://github.com/openstack/neutron.git',
                 'cisco': 'https://github.com/CiscoSystems/neutron.git'}
horizon_remotes =  {'origin': 'https://github.com/openstack/horizon.git',
                 'cisco': 'https://github.com/CiscoSystems/horizon.git'}
python_neutronclient_remotes = \
         {'origin': 'https://github.com/openstack/python-neutronclient.git',
          'cisco': 'https://github.com/CiscoSystems/python-neutronclient.git'}

neutron_upstream_branch = {'tag':'2013.2.2', 'name':'upstream-2013.2.2'}
horizon_upstream_branch = {'tag':'2013.2.2', 'name':'upstream-2013.2.2'}
python_neutronclient_upstream_branch = {'tag':'2.3.1', 
                                        'name':'upstream-2.3.1'}

neutron_cisco_branch = 'n1k-2013.2.2'
horizon_cisco_branch = 'n1k-2013.2.2'
python_neutronclient_cisco_branch = '2.3.3-n1k-havana-dev'

stack_dir = '/tmp/stack'
neutron_dir = 'neutron/'
horizon_dir = 'horizon/'
python_neutronclient_dir = 'python-neutronclient/'

neutron_rpm_pkg = 'openstack-neutron.noarch'
horizon_rpm_pkg = 'openstack-dashboard.noarch'
python_neutronclient_rpm_pkg = 'python-neutronclient.noarch'

TOPDIR = '/tmp/rpmbuild/'

banner_fmt = '''
    *******************************************************
    * %s *
    *******************************************************'''
error_fmt = '''
    !!!!! %s !!!!!'''

debug = True

def repackage(rpm_pkg, comp_dir, comp_remotes, upstream_branch, cisco_branch):
    # download and unpack redhat rpm
    rpm_dir_path = unpack_rpm(rpm_pkg)

    comp_repo_path = os.path.join(stack_dir, comp_dir)
    if os.path.exists(comp_repo_path):
        run_cmd_line('rm -rf %s'%comp_repo_path, shell=True)
    # clone upstream repo
    clone_git_repo(stack_dir, comp_remotes['origin'])
    # checkout branch from upstream tag
    checkout_branch(comp_repo_path, 
                    upstream_branch['name'], 
                    upstream_branch['tag'])
    # pull cisco repo
    pull_remote(comp_repo_path, comp_remotes)
    deltas = []
    if not comp_dir == python_neutronclient_dir:    
        # checkout develop branch
        checkout_branch(comp_repo_path, cisco_branch)
        # run cherry to get the deltas
        deltas = cherry(comp_repo_path, 
                        upstream_branch['name'], 
                        cisco_branch)
        if debug: pprint(deltas)        
        # move to upstream branch
        checkout_branch(comp_repo_path, upstream_branch['name'])
    else:
        # According to the discussion, 
        # for python-neutronclient, we only pick our commits to patch,
        # which is hard-coded here 
        deltas.append('7932447a633247408530c7baa99b055f52f7e882')

    # apply redhat patches
    apply_redhat_patches(comp_repo_path, rpm_dir_path)
    # cherry pick deltas
    cherry_pick(comp_repo_path, deltas)
    # create tar ball
    files = os.listdir(rpm_dir_path)
    for name in files:
        if fnmatch.fnmatch(name, '*.tar.gz'):
            tar_filename = name
            break
    os.chdir(stack_dir)
    # folder's name has to be %{rpmname}-%{rpmversion}
    # tarball's name has to be %{rpmname}-%{rpmversion}.tar.gz
    run_cmd_line('mv %s %s'%(comp_dir, tar_filename[:-len('.tar.gz')]))
    run_cmd_line('tar -cvzf %s %s'%
                 (tar_filename,tar_filename[:-len('.tar.gz')]))
    run_cmd_line('mv %s %s'%(tar_filename[:-len('.tar.gz')], comp_dir))
    # build rpm
    rpmbuild(rpm_dir_path, os.path.join(stack_dir, tar_filename))


def rpmbuild(rpm_dir_path, tar_filepath):
    '''
    update spec file,
    create TOPDIR,
    copy over sources and spec,
    then build rpm
    '''
    print_banner('   build rpm   ')
    os.chdir(rpm_dir_path)
    files = os.listdir('.')
    for name in files:
        if fnmatch.fnmatch(name, '*.spec'):
            spec_filename = name
            break
    # updating spec file
    with open(spec_filename, 'r') as f_old, \
         open('tmp.spec', 'w') as f_new:
        for line in f_old:
            if re.match(r'.*patch00.*', line, re.IGNORECASE):
                f_new.write('#'+line)
                continue
            elif line.find('neutron.egg-info/SOURCES.txt') != -1:
                f_new.write('#'+line)
                continue
            elif line.startswith('Source0:'):
                tar_filename = line.split('/')[-1]
                f_new.write('Source0:\t%s'%tar_filename)
                continue
            else:
                f_new.write(line)
    # create topdir
    if os.path.exists(TOPDIR):
        run_cmd_line('rm -rf %s'%TOPDIR, shell=True)        
    os.mkdir(TOPDIR)
    os.chdir(TOPDIR)
    for subdir in 'RPMS SRPMS BUILD SOURCES SPECS tmp'.split():
        os.mkdir(subdir)
    # copy over payload
    for filename in os.listdir(rpm_dir_path):
        if not fnmatch.fnmatch(filename, '*.spec') and \
           not fnmatch.fnmatch(filename, '*.patch') and \
           not fnmatch.fnmatch(filename, '*.tar.gz'):
            run_cmd_line('cp %s/%s %s' %
                          (rpm_dir_path, filename,
                           os.path.join(TOPDIR,'SOURCES')),
                         shell=True)
    # copy over tarball
    run_cmd_line('cp %s %s' %
                 (os.path.join(stack_dir,tar_filepath),
                  os.path.join(TOPDIR,'SOURCES')), shell=True)
    # copy over spec file
    run_cmd_line('mv %s %s' %
                 (os.path.join(rpm_dir_path,'tmp.spec'), 
                  os.path.join(TOPDIR,'SPECS',spec_filename)),
                 shell=True)
    # rpmbuild
    run_cmd_line('rpmbuild --define "_topdir %s" -ba %s' %
                 (TOPDIR,os.path.join(TOPDIR,'SPECS',spec_filename)),
                 shell=True)
    

def clone_git_repo(stack_dir, repo):
    print_banner('    clone %s    '%repo)
    try:
        os.chdir(stack_dir)
    except OSError as e:
        if e.errno == 2:
            os.mkdir(stack_dir)
            os.chdir(stack_dir)
        else:
            sys.exit(e.errno)

    run_cmd_line('git clone %s'%repo)


def pull_remote(repo_dir, remotes):
    print_banner('    pull remote repos    ')
    os.chdir(repo_dir)
    output, rc = run_cmd_line('git remote -v')
    output = output.split('\n')
    current_remotes = {}
    for line in output:
        if line:
            tokens = line.split()
            current_remotes[tokens[0]] = tokens[1]
    for key in remotes.keys():
        if not key in current_remotes:
            run_cmd_line('git remote add %s %s' % (key, remotes[key]))
            run_cmd_line('git fetch %s' % key)


def checkout_branch(repo_dir, branch, tag=None):
    print_banner('    checkout %s branch %s    ' % (repo_dir, branch))
    os.chdir(repo_dir)
    if tag:
        run_cmd_line('git checkout -b %s %s'%(branch, tag))
    else:
        run_cmd_line('git checkout %s' % branch)


def cherry(repo_dir, upstream_branch, develop_branch):
    print_banner('    cherry the deltas between %s and %s    '%
                 (upstream_branch, develop_branch))
    os.chdir(repo_dir)
    output_co, rc = run_cmd_line('git checkout %s' % develop_branch)
    output_cherry, rc = run_cmd_line('git cherry %s' % upstream_branch)
    deltas = []
    for line in output_cherry.split('\n'):
        if line.startswith('+'):
            deltas.append(line[1:].strip())
    return deltas


def cherry_pick(repo_dir, deltas):
    '''
    cherry pick the commits in deltas
    make sure it's in right branch when this function is called
    '''
    print_banner('    cherry pick deltas   ')
    os.chdir(repo_dir)
    for delta in deltas:
        output_pick, rc = run_cmd_line('git cherry-pick %s' % delta)


def apply_redhat_patches(repo_dir, rpmdir):
    '''
    apply redhat patches in rpmdir,
    make sure it's in right branch when this function is called
    '''
    print_banner('    apply redhat patches in %s   '%rpmdir)
    os.chdir(repo_dir)
    files = os.listdir(rpmdir)
    for afile in sorted(files):
        if afile.endswith('.patch'):
            while 'c' in run_cmd_line('git apply --ignore-whitespace %s'
                         %os.path.join(rpmdir,afile)):
                pass


def unpack_rpm(pkg):
    '''
    download and unpack rpm
    pkg as openstack-neutron.noarch
    '''
    print_banner('    download and unpack rpm   ')
    rpm_path = os.path.join('/tmp/rpm', pkg.split('.')[0])
    if os.path.exists(rpm_path):
        run_cmd_line('rm -rf %s'%rpm_path, shell=True)
    if not os.path.exists('/tmp/rpm'):
        os.mkdir('/tmp/rpm')
    os.mkdir(rpm_path)
    os.chdir(rpm_path)
    # download pkg
    run_cmd_line('yumdownloader --source %s'%pkg)
    # unpack pkg
    filename = os.listdir('.')[0]
    run_cmd_line('rpm2cpio %s | cpio -idmv'%filename, shell=True)
    return rpm_path


def print_date():
    output, rc = run_cmd_line('date --utc', echo_cmd=False, check_result=False)
    print output


def print_banner(msg):
    print banner_fmt % msg
    print_date()


def print_error(err):
    print error_fmt % err


def run_cmd_line(cmd, stderr=None, shell=False, echo_cmd=True,
                 check_result=True):
    if echo_cmd:
        print '#', cmd
    if not shell:
        cmd_args = cmd.split()
    else:
        cmd_args = cmd

    output = None
    rc = 0
    try:
        output = subprocess.check_output(cmd_args,
                                         stderr=stderr,
                                         shell=shell)
    except subprocess.CalledProcessError as e:
        if check_result:
            print_error(e)
            if 'cherry-pick' in e.cmd or 'apply' in e.cmd:
                resume = ''
                while resume not in ('c', 'n') :
                    resume = raw_input(
                               'please resolve the conflict and \
press "c" or "n": ')
                return resume, e.returncode
            else:
                sys.exit(e.returncode)
        else:
            rc = e.returncode
    return output, rc
           

if __name__ == '__main__':
    print sys.argv
    if 'neutron' in sys.argv:
        repackage(neutron_rpm_pkg, 
                  neutron_dir, 
                  neutron_remotes, 
                  neutron_upstream_branch, 
                  neutron_cisco_branch)
    if 'python-neutronclient' in sys.argv:
        repackage(python_neutronclient_rpm_pkg, 
                  python_neutronclient_dir, 
                  python_neutronclient_remotes, 
                  python_neutronclient_upstream_branch, 
                  python_neutronclient_cisco_branch)
