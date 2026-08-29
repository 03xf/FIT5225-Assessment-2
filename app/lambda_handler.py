"""AWS Lambda entry point for the authenticated REST API container."""

from mangum import Mangum

from app.main import app

# Lifespan is managed by Mangum for each warm Lambda execution environment.
handler = Mangum(app, lifespan="auto")
