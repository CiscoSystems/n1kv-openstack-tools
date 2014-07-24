# author: Aaron Zhang (fenzhang)

import argparse
import os
import pickle
import subprocess
import sys
import smtplib

comps = ['neutron', 'python-neutronclient', 'horizon']
rmadison_cmd = 'rmadison %(comp)s | grep "%(ppa)s "'

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--ppa', required = True,
                        help = 'ppa to grep version')
    parser.add_argument('-f', '--filepath', required = True,
                        help = 'the file to store versions')
    args = parser.parse_args()

    changes = {}
    try:
        versions = pickle.load(open(args.filepath))
    except Exception:
        versions = {}
        pass
    for comp in comps:
        try:
            output = subprocess.check_output(rmadison_cmd % {'comp': comp,
                                                             'ppa': args.ppa},
                                             shell=True)
            # e.g. "neutron | 1:2014.1.1-0ubuntu2   | trusty-updates  | source"
            version, release = output.split('|')[1].split(':')[1].split('-')
            if versions.get(comp, None) != version:
                changes[comp] = {'old': versions.get(comp, None), 'new': version}
                versions[comp] = version
        except subprocess.CalledProcessError as e:
            # info for this comp and ppa doesn't exist
            print e
        except KeyError:
            # previous comp version info doesn't exist
            versions[comp] = version
    if changes:
        # send email
        print 'change set: %s' % changes
        subprocess.check_output('ssh chingwei@10.28.28.132 mail -s %s fenzhang@cisco.com cwchang@cisco.com' % changes,
                                shell=True)

    with open(args.filepath, 'w') as f:
        pickle.dump(versions, f)
