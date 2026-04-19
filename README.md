# NWO Conway Bridge Relayer

## Deploy to Render

### 1. Create GitHub Repo

Upload these files to GitHub:
- `relayer.py`
- `requirements.txt`
- `Dockerfile`

### 2. Deploy on Render

1. Go to https://dashboard.render.com
2. Click "New Web Service"
3. Connect your GitHub repo
4. Settings:
   - **Runtime**: Docker
   - **Plan**: Starter ($7/month) for 24/7

### 3. Environment Variables

Add these in Render dashboard:

```
BASE_RPC=https://mainnet.base.org
ETH_RPC=https://mainnet.infura.io/v3/YOUR_INFURA_KEY
RELAYER_KEY=0x...  # Private key for 0x57C508Db6e53dd93A34C85277c27Fb37dc45c108
```

### 4. Fund Relayer Wallet

Send ETH to: **0x57C508Db6e53dd93A34C85277c27Fb37dc45c108**

- **Base**: 0.01 ETH for gas
- **Ethereum**: 0.05 ETH for gas

### 5. Deploy!

Click "Create Web Service"

## How It Works

1. Agent on Base calls `purchaseAPITier()`
2. Relayer detects payment intent
3. Relayer sends ETH to NWO contract on Ethereum
4. Relayer confirms on Base
5. Agent gets API credits!

## Monitoring

Check logs in Render dashboard for:
- Pending intents detected
- Ethereum transactions
- Confirmations on Base

## Contract Addresses

- **Base Contract**: 0xC699b07f997962e44d3b73eB8E95d5E0082456ac
- **NWO API (Ethereum)**: 0x1ed4A655F622c09332fA7a67e3F449fe591BC9F6
- **Relayer**: 0x57C508Db6e53dd93A34C85277c27Fb37dc45c108