# 📈 Stock Market Analysis Dashboard

A free, full-featured stock analysis tool for Indian markets (NSE/BSE).

## Features

- Interactive candlestick charts with 50-DMA, 200-DMA, support/resistance
- Earnings date warnings
- 1% risk position sizing calculator
- AI-powered news catalyst summaries (via Google Gemini)

## Deploy to Streamlit Community Cloud (Free)

### Step 1: Push to GitHub

1. Create a new GitHub repository (public or private).
2. Upload all project files maintaining this structure:

```
your-repo/
├── app.py
├── requirements.txt
├── .streamlit/
│   └── config.toml
└── README.md
```

3. Commit and push.

### Step 2: Deploy on Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **"New app"**.
3. Select your repository, branch (`main`), and main file (`app.py`).
4. Click **"Deploy"**.

### Step 3: (Optional) Add Gemini API Key as a Secret

1. Get a free API key from [aistudio.google.com](https://aistudio.google.com).
2. In your Streamlit Cloud app dashboard, go to **Settings → Secrets**.
3. Add:

```toml
GEMINI_API_KEY = "your-api-key-here"
```

4. Alternatively, paste the key into the sidebar input field at runtime.

### Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Disclaimer

This tool is for **educational purposes only**. It is not financial advice.
