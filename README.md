# octopus-scripts

This repository contains scripts that are used to automate retrieval of information from Octopus Deploy.

Before running the script, you need to install the required packages by running the following command:

```bash
pip install pytz
export OCTOPUS_API_KEY=<your_octopus_api_key>

```
You will also need to enter in the Space ID and Octopus URL in the script.

## octopus_deploy_projects.py
This script is used to retrieve the list of projects in Octopus Deploy and most current release/deployment for each project. If the deployment is unsuccessful it will look for the next successful deployment.

It will output two files, one called debug_log.txt which contains the logs of the script and the other called all_projects_deployment_data.json which contains the data of the projects and their deployments grouped by project groups (if any).

You can then take this information and send it elsewhere, or create a csv file with the data. I personally send it to confluence to update a table with the latest deployments.