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
5. push-rpm-to-yum and rpmsign.expect
   script to push files to yum repo
6. openstack-neutron-%{version}.%{release}.src.rpm and python-neutronclient-%{version}.%{release}.src.rpm
   optional
   these are rdo rpms from which we build packages when osp5 is not available. 
7. README_packaging.txt
   README file


All these files should be in the same folder to make them work.
make sure all the scripts have right mode.
