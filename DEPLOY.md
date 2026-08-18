# Deployment Guide - Railway.app

## ✅ Updated Configuration

Your project now has:
- ✅ `Procfile` - production WSGI server configuration
- ✅ `Dockerfile` - containerized deployment
- ✅ `railway.json` - Railway-specific settings
- ✅ `requirements.txt` - all dependencies including gunicorn
- ✅ `.env` - configured with API keys
- ✅ `app.py` - optimized for cloud deployment

## Quick Deployment Steps

### Step 1: Push to GitHub

```bash
cd c:\Users\saber\OneDrive\Desktop\finall\clinical-rag

# If not already initialized
git init
git add .
git commit -m "Clinical RAG - Medical Q&A System"
git branch -M main

# Create repo at github.com/new, then push:
git remote add origin https://github.com/YOUR_USERNAME/clinical-rag.git
git push -u origin main
```

### Step 2: Deploy on Railway

1. Go to **[railway.app](https://railway.app)**
2. Sign in with GitHub
3. Click **"New Project"** → **"Deploy from GitHub repo"**
4. Select your `clinical-rag` repository
5. Railway automatically detects `Dockerfile` and deploys! ✅

### Step 3: Add Environment Variables

In Railway Dashboard:
1. Click your project → **"Variables"** tab
2. Add your `.env` variables one by one:

```
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile
QDRANT_URL=https://your-qdrant-url.eu.cloud.qdrant.io
QDRANT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
QDRANT_COLLECTION=clinical-rag
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxxxxxxxxxx
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=medical-guideline-rag
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
CHUNK_SIZE=900
CHUNK_OVERLAP=150
TOP_K=3
FLASK_ENV=production
```

### Step 4: Get Your Live URL

Once deployment completes (2-5 minutes):
- Railway gives you a URL like: `https://clinical-rag-production.up.railway.app`
- Your app is LIVE! 🌍

---

## Troubleshooting

### "The train has not arrived at the station"
- This means the deployment is still in progress or failed
- Check Railway Dashboard **"Deployments"** tab for logs
- Common fixes:
  1. Ensure all env vars are set correctly
  2. Check logs for Python errors
  3. Try triggering a manual redeploy

### "Build failed"
- Check build logs in Railway Dashboard
- Ensure `requirements.txt` has all dependencies
- Verify `Dockerfile` exists

### "App crashes on startup"
- Check "Logs" tab in Railway Dashboard
- Verify `GROQ_API_KEY` and `QDRANT_URL` are set
- Ensure PDFs exist in `data/` folder (commit them to GitHub)

---

## Important Notes

⚠️ **SQLite Database Limitation**
- Railway has ephemeral storage - database resets on redeploy
- For production: use Railway PostgreSQL add-on or managed database
- Current setup: good for testing/demos

⚠️ **PDF Storage**
- PDFs must be committed to GitHub
- They'll be included in the Docker image
- For large files: use cloud storage (S3, Azure Blob)

⚠️ **Security**
- NEVER commit `.env` to GitHub
- Always use Railway's "Variables" dashboard
- Review API key access logs regularly

---

## Monitoring

In Railway Dashboard:
- **Deployments** - deployment history
- **Logs** - real-time application logs
- **Metrics** - CPU, memory, network usage
- **Environment** - manage variables safely

---

## Next Steps

After successful deployment:
1. Visit your live URL
2. Create an account
3. Upload user profile
4. Ask medical questions
5. System searches PDFs + calls Groq LLM
6. Get AI-powered medical guidance!

---

Need help? Railway docs: https://docs.railway.app
