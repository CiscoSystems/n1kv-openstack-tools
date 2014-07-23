Author: Aaron Zhang(fenzhang)

The purpose of this scripting is to re-package redhat's rdo/osp5 rpms with cisco plugin's changes (which are not merged
and back ported in stable/icehouse yet) and push the new packages to internal yum repo.

This scription includes the following scripts:
1. monitor.cron
   cron job script. crontab will execute this script;
2. monitor.py
   the major monitor logic script. It takes care of invoking packaging script, creating backup folders and pushing 
   packages onto internal yum repo;
3. packaging_v2.py
   packaging script. This script does all the downloading, unpacking, patching and building work;
4. packaging.conf
   config file, which has all the env settings 
   [general]
   stack_dir: where the n1kv openstack code will be stored
   rpm_dir: where the rpm package will be unpacked to
   TOPDIR: staging dir. All resources will be moved here and then be built
   dump_dir: location to keep daily builds
   [neutron/python-neutronclient/horizon]
   component: name of the component
   origin_remote: the upstream repo url
   cisco_remote: cisco repo url
   upstream_tag: the tag the base code uses. This needs to be updated once OSP moves the base tag.
   cisco_branch: cisco branch from where we collect n1kv openstack code. This needs to be updated once a new cisco branch is created for the upstream_tag
   rpm_pkg: the rpm package in OSP
5. push-rpm-to-yum and rpmsign.expect
   script to push files to yum repo
6. openstack-neutron-%{version}.%{release}.src.rpm and python-neutronclient-%{version}.%{release}.src.rpm
   optional
   these are rdo rpms from which we build packages when osp5 is not available. 
7. README_packaging.txt
   README file


All these files should be in the same folder to make them work.
make sure all the scripts have right mode.
