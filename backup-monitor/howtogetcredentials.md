## Here are the steps to obtain and use the `client_secrets.json` file:

## Step 1: Obtain client_secrets.json File
1.1 Go to the Google Cloud Console:

1.2 Visit Google Cloud Console.

1.3 Create a New Project or Select an Existing Project.

1.4 Enable the Google Drive API:

1.5 Navigate to the "APIs & Services" > "Library".

1.6 Search for "Google Drive API".

1.7 Click "Enable".

1.8 Create OAuth 2.0 Credentials:

1.9 Go to "APIs & Services" > "Credentials".

1.10 Click on "Create Credentials" > "OAuth 2.0 Client IDs".

1.11 Configure the consent screen if prompted.

1.12 Set the application type to "Desktop app".

1.13 Download the JSON file (it will be named `client_secrets.json`).

## Step 2: Rename and Place client_secrets.json in the same Directory of `get-credentials.py` script
2.1 Place the downloaded client_secrets.json file in the same directory as your script (credentials.py).
## Step 3: Update and Run on a machine with a `web browser` the `get-credentials.py` Script
3.1 A webpage will prompt you to authenticate with your google account
3.2 Copy the `credentials.json` file on your local machine to backup-monitor folder
