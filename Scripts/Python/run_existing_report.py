#
#  Python script using OME API to run a pre-defined report
#
# _author_ = Raajeev Kalyanaraman <Raajeev.Kalyanaraman@Dell.com>
# _version_ = 0.1
#
# Copyright (c) 2018 Dell EMC Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""
SYNOPSIS:
    Allow execution of a pre-defined report in OME
    and print out report results to screen

DESCRIPTION:
    Allow execution of a pre-defined report including custom
    reports in OpenManage Enterprise.
    Output results are presented in a csv format to collate
    column names with the results

    Note: The group id argument is optional and is unused
    in the report execution API at this time.

API WORKFLOW:
    1: POST on SessionService/Sessions
    2: If new session is created (201) parse headers
    for x-auth token and update headers with token
    3: All subsequent requests use X-auth token and not
    user name and password entered by user
    4: POST on ReportService.RunReport method
    Parameters are the ID of the report to run
    5: if method execution is successful returned
    response presents a job id to track status
    6: GET on JobService/Jobs(<jobid>) and poll
    returned job status until completion
    7: On success GET on ReportService/ReportDefs(ID)
    to determine column names for the report
    8: Extract report results (GET) at /ReportResults/ResultRows
    and print out results

EXAMPLE:
    python .\run_existing_report.py  --ip <ip addr> --user <username>
        --password <password> --reportid 10051
"""
import sys
import argparse
from argparse import RawTextHelpFormatter
import json
import time
import requests
import urllib3


class OMEReportExecutor(object):
    """ Execute an existing OME Report including custom reports """

    def __init__(self, ip_address, user_name, password,
                 report_id, group_id=0):
        """ Constructor for class OMEReportExecutor """
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.ip_address = ip_address
        self.user_name = user_name
        self.password = password
        self.report_id = report_id
        self.group_id = group_id
        self.base_url = 'https://%s/api/' % (self.ip_address)

    def authenticate_with_ome(self):
        """ X-auth session creation """
        auth_success = False
        ip_address = self.ip_address
        session_url = self.base_url + "SessionService/Sessions"
        user_details = {'UserName': self.user_name,
                        'Password': self.password,
                        'SessionType': 'API'}
        headers = {'content-type': 'application/json'}
        session_info = requests.post(session_url, verify=False,
                                     data=json.dumps(user_details),
                                     headers=headers)
        if session_info.status_code == 201:
            headers['X-Auth-Token'] = session_info.headers['X-Auth-Token']
            auth_success = True
        else:
            error_msg = "Failed create of session with {0} - Status code = {1}"
            print (error_msg.format(ip_address, session_info.status_code))
        return (auth_success, headers)

    def execute_report(self, headers):
        """ Execute a given report id for the user and track job """
        report_base_url = self.base_url + "ReportService/Actions/"
        report_exec_url = report_base_url + "ReportService.RunReport"
        report_body = {'ReportDefId': self.report_id,
                       'FilterGroupId': self.group_id}
        job_done_status = ["completed", "failed", "warning",
                           "aborted", "canceled"]
        max_retry_count = 90
        print ("Executing report", self.report_id)
        report_exec_resp = requests.post(report_exec_url,
                                         headers=headers,
                                         data=json.dumps(report_body),
                                         verify=False)
        if report_exec_resp.status_code == 200:
            print ("Executed report %s successfully ..." % self.report_id)
            job_id = report_exec_resp.json()
            job_url = self.base_url + "JobService/Jobs(%s)" % (job_id)
            curr_job_status = ""
            counter = 0
            print ("Tracking job id %s for report execution ... " % (job_id))
            while counter < max_retry_count and \
                    curr_job_status not in job_done_status:
                counter += 1
                time.sleep(10)
                job_response = requests.get(job_url,
                                            headers=headers,
                                            verify=False)
                if job_response.status_code == 200:
                    job_info = job_response.json()
                    curr_job_status = job_info['LastRunStatus']['Name'].lower()
                    print ("Job status : ", curr_job_status)
                else:
                    print ("Unable to get status for job ", job_id)
            if curr_job_status == "completed":
                print ("Job %s completed successfully ... " % (job_id))
                self.format_output_report(headers)
        else:
            print ("Unable to execute report ", self.report_id)

    def format_output_report(self, headers):
        """ Pretty print report and associated column names """
        report_url_suffix = "ReportService/ReportDefs(%s)" % (self.report_id)
        report_details_url = self.base_url + report_url_suffix
        report_details_resp = requests.get(report_details_url,
                                           headers=headers,
                                           verify=False)
        if report_details_resp.status_code == 200:
            report_details_info = report_details_resp.json()
            column_info_arr = report_details_info['ColumnNames']

            column_names = [x['Name'] for x in column_info_arr]
            print (",".join(column_names))
            result_url = report_details_url + "/ReportResults/ResultRows"
            report_result = requests.get(result_url,
                                         headers=headers,
                                         verify=False)
            if report_result.status_code == 200:
                report_info = report_result.json()
                total_rep_results = report_info['@odata.count']
                if total_rep_results > 0:
                    current_rep_result_count = len(report_info['value'])
                    if total_rep_results >current_rep_result_count:
                        delta = total_rep_results - current_rep_result_count
                        remaining_res_url = result_url +"?$skip=%s&$top=%s"%(current_rep_result_count, delta)
                        rem_res_resp = requests.get(remaining_res_url, headers=headers, verify = False)
                        if rem_res_resp.status_code ==200:
                            rem_resp_info = rem_res_resp.json()
                            for value in rem_res_info['value']:
                                report_info['value'].append(value)
                        else:
                            print("Unable to get full set of report results")        
                    for result in report_info['value']:
                        print (",".join(result['Values']))
                else:
                    print ("No report data found for %s" % (self.report_id))
            else:
                print ("No result data for report %s", self.report_id)
        else:
            print ("Unable to extract report definitions from ", self.ip_address)

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=RawTextHelpFormatter)
    PARSER.add_argument("--ip", "-i", required=True,
                        help="OME Appliance IP")
    PARSER.add_argument("--user", "-u", required=True,
                        help="Username for OME Appliance",
                        default="admin")
    PARSER.add_argument("--password", "-p", required=True,
                        help="Password for OME Appliance")
    PARSER.add_argument("--reportid", "-r", required=True,
                        help="a valid report id to execute")
    PARSER.add_argument("--groupid", "-g", required=False,
                        default=0,
                        help="Optional param - Group id to run report against")
    ARGS = PARSER.parse_args()

    try:
        REPORT_EXEC = OMEReportExecutor(ARGS.ip, ARGS.user,
                                        ARGS.password,
                                        ARGS.reportid,
                                        ARGS.groupid)
        AUTH_STATUS, SESS_HEADERS = REPORT_EXEC.authenticate_with_ome()
        if AUTH_STATUS:
            REPORT_EXEC.execute_report(SESS_HEADERS)
    except:
        print ("Unexpected error:", sys.exc_info())
