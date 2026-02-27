#!/bin/bash
apt-get update
apt-get install -y curl gpg
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/cloudflare-client.list
apt-get update && apt-get install -y cloudflare-warp
warp-cli --accept-tos register
warp-cli --accept-tos set-mode warp
warp-cli --accept-tos connect
sleep 3
curl -4 https://cloudflare.com/cdn-cgi/trace
