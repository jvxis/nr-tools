from pydrive.auth import GoogleAuth

gauth = GoogleAuth()
gauth.LoadClientConfigFile("client_secrets.json")
gauth.LocalWebserverAuth()  # Creates local webserver and handles authentication
gauth.SaveCredentialsFile("credentials.json")  # Save the credentials to a file
