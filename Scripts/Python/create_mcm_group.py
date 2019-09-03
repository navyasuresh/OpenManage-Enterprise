import argparse
import json
import requests
import urllib3
from argparse import RawTextHelpFormatter
import random
import time
import sys


"""
SYNOPSIS
---------------------------------------------------------------------
 Script to create MCM group, add all members to the created group,
 and assign a backup lead

DESCRIPTION
---------------------------------------------------------------------
 This script creates a MCM group, adds all standalone domains to the
 created group and assigns a member as backup lead.

 Note:
 1. Credentials entered are not stored to disk.
 2. Passed in argument 'ip' becomes the lead in the created MCM group
 
EXAMPLE
---------------------------------------------------------------------
python create_mcm_group.py --ip <ip addr> --user root
    --password <passwd> --groupname testgroup

Creates MCM group, adds all standalone members and assign a member as
backup lead

API workflow is below:
1: POST on SessionService/Sessions
2: If new session is created (201) parse headers
   for x-auth token and update headers with token
3: All subsequent requests use X-auth token and not
   user name and password entered by user
4: Create MCM group with given group name
   with PUT on /ManagementDomainService
5: Parse returned job id and monitor it to completion
6: Add all standalone members to the created group
   with POST on /ManagementDomainService/Actions/ManagementDomainService.Domains
7: Parse returned job id and monitor it to completion
8: Assign a random member as backup lead
   with POST on /ManagementDomainService/Actions/ManagementDomainService.AssignBackupLead
9: Parse returned job id and monitor it to completion
"""

class SessionManager:
    session = None
    base_url = ''
    def get_session(self):
        if not self.session:
            self.session = requests.Session()
            self.session.headers.update({'content-type': 'application/json'})
        return self.session
    
    def get_base_url(self):
        return self.base_url
    
    def set_base_url(self, url):
        self.base_url = url


def authenticate(session_manager, username, password):
    session_url = '{0}/SessionService/Sessions'.format(session_manager.get_base_url())
    session = session_manager.get_session()
    auth_success = False
    
    user_details = {
        'UserName': username,
        'Password': password,
        'SessionType': 'API'
    }
    session_info = session.post(session_url, verify=False, json=user_details)
    if session_info.status_code == 201:
        session.headers.update({
            'X-Auth-Token': session_info.headers['X-Auth-Token'],
            'content-type': 'application/json'
        })
        auth_success = True
    else:
        print('Failed to login. Check username and password')

    return auth_success


def create_mcm_group(session_manager, group_name):
    create_group_url = '{0}/ManagementDomainService'.format(session_manager.get_base_url())
    session = session_manager.get_session()
    create_group_payload = {
        "GroupName": group_name,
        "GroupDescription": "",
        "JoinApproval": "AUTOMATIC",
        "ConfigReplication": [{
            "ConfigType": "Power",
            "Enabled": False
        }, {
            "ConfigType": "UserAuthentication",
            "Enabled": False
        }, {
            "ConfigType": "AlertDestinations",
            "Enabled": False
        }, {
            "ConfigType": "TimeSettings",
            "Enabled": False
        }, {
            "ConfigType": "ProxySettings",
            "Enabled": False
        }, {
            "ConfigType": "SecuritySettings",
            "Enabled": False
        }, {
            "ConfigType": "NetworkServices",
            "Enabled": False
        }, {
            "ConfigType": "LocalAccessConfiguration",
            "Enabled": False
        }]
    }
    group_info = session.put(create_group_url, verify=False, json=create_group_payload)
    job_id = None
    if group_info.status_code == 200:
        group_info = group_info.json()
        job_id = group_info.get('JobId')
        print('MCM group created : Job ID = {0}'.format(job_id))
    else:
        print('Failed to create MCM group with the below error')
    return job_id

def get_domains(session_manager):
    members = []
    session = session_manager.get_session()
    url = '{0}/ManagementDomainService/Domains'.format(session_manager.get_base_url())
    response = session.get(url, verify=False)
    if response.status_code == 200:
        response = response.json()
        member_devices = response.get('value')
        for member_device in member_devices:
            role = member_device.get('DomainRoleTypeValue')
            if role == 'MEMBER':
                members.append(member_device)

        if not members:
            print ('No member device found')

    else:
        print ('Failed to get domains and status code returned is %s', response.status_code)
    return members


def get_discovered_domains(session_manager, role=None):
    discovered_domains = []
    session = session_manager.get_session()
    url = '{0}/ManagementDomainService/DiscoveredDomains'.format(session_manager.get_base_url())
    domains_info = session.get(url, verify=False)
    if domains_info.status_code == 200:
        domains = domains_info.json()
        if domains.get('@odata.count') > 0:
            discovered_domains = domains.get('value')
        else:
            print ("No domains discovered ... Error")

    else:
        print('Failed to discover domains - Status Code %s')

    if role:
        discovered_domains = list(filter(lambda x: x.get(
            'DomainRoleTypeValue') == role, discovered_domains))
    return discovered_domains

def add_all_members_via_lead(session_manager):
    """ Add standalone domains to the group"""
    standalone_domains = get_discovered_domains(session_manager, role='STANDALONE')
    session = session_manager.get_session()
    job_id = None
    if standalone_domains:
        body = []
        for domain in standalone_domains:
            body.append({'GroupId': domain.get('GroupId')})

        url = '{0}/ManagementDomainService/Actions/ManagementDomainService.Domains'.format(session_manager.get_base_url())
        response = session.post(url, json=body, verify=False)
        if response.status_code == 200:
            response_data = response.json()
            job_id = response_data.get('JobId')
            print('Added members to the created group, Job ID = {0}'.format(job_id))
        else:
            print('Failed to add members to the group')
    else:
        print('No standalone chassis found to add as member to the created group')
    return job_id

def assign_backup_lead(session_manager):
    url = '{0}/ManagementDomainService/Actions/ManagementDomainService.AssignBackupLead'.format(session_manager.get_base_url())
    session = session_manager.get_session()
    members = get_domains(session_manager)
    job_id = None
    if members:
        member = random.choice(members)
        member_id = member.get('Id')
        body = [{
            'Id': member_id
        }]
        response = session.post(url, verify=False, json=body)
        if response.status_code == 200:
            response = response.json()
            job_id = response.get('JobId')
        else:
            print('Failed to assign backup lead')
    else:
        print('Created group has no members. Failed to assign a backup lead')
    return job_id

def get_job_status(session_manager, job_id):
    """ Tracks the update job to completion / error """
    session = session_manager.get_session()
    job_status_map = {
        "2020": "Scheduled",
        "2030": "Queued",
        "2040": "Starting",
        "2050": "Running",
        "2060": "Completed",
        "2070": "Failed",
        "2090": "Warning",
        "2080": "New",
        "2100": "Aborted",
        "2101": "Paused",
        "2102": "Stopped",
        "2103": "Canceled"
    }
    max_retries = 20
    sleep_interval = 60
    failed_job_status = [2070, 2090, 2100, 2101, 2102, 2103]
    job_url = '{0}/JobService/Jobs({1})'.format(session_manager.get_base_url(), job_id)
    loop_ctr = 0
    job_incomplete = True
    print ("Polling %s to completion ..." % job_id)
    while loop_ctr < max_retries:
        loop_ctr += 1
        time.sleep(sleep_interval)
        job_resp = session.get(job_url, verify=False)
        if job_resp.status_code == 200:
            job_status = str((job_resp.json())['LastRunStatus']['Id'])
            print ("Iteration %s: Status of %s is %s" % (loop_ctr, job_id, job_status_map[job_status]))
            if int(job_status) == 2060:
                job_incomplete = False
                print ("Completed job successfully ... Exiting")
                break
            elif int(job_status) in failed_job_status:
                job_incomplete = False
                print ("Job failed ... ")
                job_hist_url = str(job_url) + "/ExecutionHistories"
                job_hist_resp = session.get(job_hist_url, verify=False)
                if job_hist_resp.status_code == 200:
                    job_history_id = str((job_hist_resp.json())['value'][0]['Id'])
                    job_hist_det_url = str(job_hist_url) + "(" + job_history_id + ")/ExecutionHistoryDetails"
                    job_hist_det_resp = session.get(job_hist_det_url, verify=False)
                    if job_hist_det_resp.status_code == 200:
                        print (job_hist_det_resp.text)
                    else:
                        print ("Unable to parse job execution history .. Exiting")
                break
        else:
            print ("Unable to poll status of %s - Iteration %s " % (job_id, loop_ctr))
    if job_incomplete:
        print ("Job %s incomplete after polling %s times...Check status" % (job_id, max_retries))

def check_job_id(job_id):
    if not job_id:
        print('Job ID is null')
        sys.exit(1)

if __name__ == '__main__':
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    PARSER = argparse.ArgumentParser(description=__doc__, formatter_class=RawTextHelpFormatter)
    PARSER.add_argument("--ip", "-i", required=True, help="MSM IP")
    PARSER.add_argument("--user", "-u", required=True, help="Username for MSM", default="root")
    PARSER.add_argument("--password", "-p", required=True, help="Password for MSM")
    PARSER.add_argument("--groupname", "-g", required=True, help="A valid name for the group")
    ARGS = PARSER.parse_args()
    base_url = 'https://{0}/api'.format(ARGS.ip)

    session_manager = SessionManager()
    session_manager.set_base_url(base_url)
    try:
        if authenticate(session_manager, ARGS.user, ARGS.password):
            job_id = create_mcm_group(session_manager, ARGS.groupname)
            check_job_id(job_id)
            
            print('Polling for create group job status')
            get_job_status(session_manager, job_id)
            
            job_id = add_all_members_via_lead(session_manager)
            check_job_id(job_id)
        
            print('Polling for add members job status')
            get_job_status(session_manager, job_id)

            job_id = assign_backup_lead(session_manager)
            check_job_id(job_id)

            print('Polling for assign backup lead job status')
            get_job_status(session_manager, job_id)
        else:
            print('Unable to authenticate. Check IP/username/password')
    except:
        print ("Unexpected error:", sys.exc_info())
