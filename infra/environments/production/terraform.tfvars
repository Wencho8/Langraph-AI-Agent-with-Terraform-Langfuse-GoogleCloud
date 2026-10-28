project_id      = "wencho8-chatbot-prod"
region          = "us-central1"
sql_admin_email = "wenchoavalos8@gmail.com"
backend_image   = "us-central1-docker.pkg.dev/wencho8-chatbot-prod/chatbot/backend@sha256:fb17bb407d93120cf0eef05cd34c0e55d686ff53f00bbffd493fd8ec85543000"

# Planned Firebase Hosting origin; the frontend is not published yet.
frontend_origin       = "https://wencho8-chatbot-prod.web.app"
model                 = "openai:gpt-6.1-terra"
openai_secret_version = "1"
