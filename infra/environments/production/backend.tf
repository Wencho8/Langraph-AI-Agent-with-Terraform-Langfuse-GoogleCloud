terraform {
  backend "gcs" {
    bucket = "wencho8-chatbot-prod-tfstate"
    prefix = "environments/production"
  }
}
