# GCP Commands

**Validate Models Available**

**Visit** : https://console.cloud.google.com/vertex-ai/model-garden?project=ragai-staging

Or **execute in terminal**

All models with response `200` are available

```
for model in gemini-2.5-flash gemini-2.5-flash-lite gemini-2.5-pro gemini-2.0-flash gemini-2.0-flash-lite gemini-2.0-pro gemini-1.5-flash gemini-1.5-flash-8b gemini-1.5-pro gemini-3.5-flash gemini-3.1-pro-preview gemini-3.1-flash gemini-3.1-flash-lite; do
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "Content-Type: application/json" \
    -d '{"contents":[{"role":"user","parts":[{"text":"hi"}]}]}' \
    "https://aiplatform.googleapis.com/v1beta1/projects/ragai-staging/locations/global/publishers/google/models/${model}:generateContent")
  echo "$model: $code"
done
```

**Build + Deploy + IAM:**
Run in terminal

```
cd ~/Documents/Work/Devops/wiso-rag/wisorag-corrections
git checkout develop
git pull origin develop

gcloud builds submit \
    --tag us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest \
    --project=ragai-staging . && \
gcloud run deploy wiso-ai-api \
    --image=us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest \
    --region=us-central1 \
    --platform=managed \
    --no-allow-unauthenticated \
    --service-account=rag-api-sa@ragai-staging.iam.gserviceaccount.com \
    --set-secrets=ALLOYDB_PASSWORD=ALLOYDB_PRIMARY_PASSWORD:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest \
    --set-env-vars=ALLOYDB_HOST=10.187.0.2,ALLOYDB_DATABASE=wiso_ai_db,ALLOYDB_USER=postgres,VERTEX_AI_PROJECT=ragai-staging,VERTEX_AI_LOCATION=us-central1,BIGQUERY_PROJECT=simula-ipd-produ,ENVIRONMENT=dev \
    --vpc-connector=wiso-ai-vpc-connector \
    --vpc-egress=all-traffic \
    --min-instances=1 \
    --max-instances=10 \
    --memory=2Gi \
    --cpu=2 \
    --timeout=60 \
    --concurrency=80 && \
gcloud run services add-iam-policy-binding wiso-ai-api \
    --region=us-central1 \
    --project=ragai-staging \
    --member="allUsers" \
    --role="roles/run.invoker"
```
