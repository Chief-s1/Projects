import requests

# Replace these with your Control-M details
CONTROL_M_HOST = 'http://<controlm-server>:<port>'
USERNAME = 'your_username'
PASSWORD = 'your_password'

# Job/Folder details
FOLDER_NAME = 'YourFolderName'     # Required
JOB_NAME = 'YourJobName'           # Optional – omit if ordering full folder

# Step 1: Login to get auth token
def get_token():
    login_url = f"{CONTROL_M_HOST}/automation-api/session/login"
    response = requests.post(login_url, json={
        'username': USERNAME,
        'password': PASSWORD
    })

    if response.status_code == 200:
        return response.json()['token']
    else:
        raise Exception(f"Login failed: {response.status_code}, {response.text}")

# Step 2: Order the job or folder
def order_job(token):
    order_url = f"{CONTROL_M_HOST}/automation-api/run/order"
    headers = {'Authorization': f'Bearer {token}'}

    payload = {
        "folder": FOLDER_NAME
    }
    if JOB_NAME:
        payload["jobname"] = JOB_NAME

    response = requests.post(order_url, headers=headers, json=payload)

    if response.status_code == 200:
        print("Job ordered successfully!")
        print(response.json())
    else:
        raise Exception(f"Ordering failed: {response.status_code}, {response.text}")

# Main runner
if __name__ == '__main__':
    try:
        token = get_token()
        order_job(token)
    except Exception as e:
        print(f"Error: {e}")