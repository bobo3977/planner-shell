#!/bin/bash

# ==========================================================
# planner-shell: Secure AI DevOps Agent Setup Script
# ==========================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BLUE}${BOLD}🚀 Starting planner-shell Secure Setup...${NC}"

# 1. uv check
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

# 2. Sync & Install
echo -e "${BLUE}📦 Installing planner-shell...${NC}"
uv sync
uv pip install -e .

# 3. Secure Environment Configuration (.env)
if [ ! -f .env ]; then
    echo -e "${YELLOW}📝 Creating .env from template...${NC}"
    if [ -f .env.example ]; then
        cp .env.example .env
    else
        touch .env
    fi
    # --- SECURITY UPGRADE START ---
    chmod 600 .env
    echo -e "${GREEN}🔒 .env created with restricted permissions (chmod 600).${NC}"
    # --- SECURITY UPGRADE END ---
else
    # Ensure existing .env is also secured
    chmod 600 .env
    echo -e "ℹ️ .env already exists. Permissions have been updated to 600."
fi

# 4. Alias Fallback
CURRENT_DIR=$(pwd)
MARKER="# planner-shell configuration"
ALIAS_LINE="alias planner-shell='uv --project $CURRENT_DIR run planner-shell'"

if ! grep -q "$MARKER" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "$MARKER" >> ~/.bashrc
    echo "$ALIAS_LINE" >> ~/.bashrc
fi

echo -e "${BLUE}----------------------------------------------------------${NC}"
echo -e "${GREEN}${BOLD}🎉 Setup Complete & Secured!${NC}"
echo -e "Permissions for ${YELLOW}.env${NC} have been set to ${BOLD}600${NC}."
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT:${NC}"
echo -e "  1. Edit ${YELLOW}.env${NC} and add your API keys:"
echo -e "     ${BOLD}OPENAI_API_KEY${NC} or ${BOLD}OPENROUTER_API_KEY${NC}"
echo -e "     (and ${BOLD}TAVILY_API_KEY${NC} if you want web search)"
echo -e "  2. Start the agent: ${GREEN}${BOLD}planner-shell${NC}"
echo -e "${BLUE}----------------------------------------------------------${NC}"

source ~/.bashrc
