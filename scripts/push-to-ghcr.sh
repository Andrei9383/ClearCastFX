#!/bin/bash
# Push locally-built BluCast container to GitHub Container Registry
#
# Prerequisites:
#   1. Build the container locally first: ./install.sh
#   2. Create a GitHub Personal Access Token (PAT) with 'write:packages' scope
#      https://github.com/settings/tokens/new?scopes=write:packages
#
# Usage:
#   ./scripts/push-to-ghcr.sh
#
# The script will prompt for your GitHub username and PAT.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

LOCAL_IMAGE="localhost/blucast:latest"
GHCR_IMAGE="ghcr.io/andrei9383/blucast"

# Detect container runtime
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
else
    CONTAINER_CMD="docker"
fi

echo -e "${BLUE}"
echo "======================================"
echo "   Push BluCast to GHCR"
echo "======================================"
echo -e "${NC}"

# Check if local image exists
if ! $CONTAINER_CMD image exists "$LOCAL_IMAGE" 2>/dev/null && \
   ! $CONTAINER_CMD inspect "$LOCAL_IMAGE" &>/dev/null; then
    echo -e "${RED}Error: Local image not found${NC}"
    echo -e "Build first with: ${BLUE}./install.sh${NC}"
    exit 1
fi

echo -e "${GREEN}Found local image: $LOCAL_IMAGE${NC}"
echo ""

# Get GitHub credentials
echo -e "${YELLOW}GitHub Container Registry Login${NC}"
echo ""
echo "You need a Personal Access Token (PAT) with 'write:packages' scope."
echo "Create one at: https://github.com/settings/tokens/new?scopes=write:packages"
echo ""

read -p "GitHub Username: " GITHUB_USER
read -sp "GitHub PAT: " GITHUB_TOKEN
echo ""

# Login to GHCR
echo ""
echo -e "${YELLOW}Logging in to ghcr.io...${NC}"
echo "$GITHUB_TOKEN" | $CONTAINER_CMD login ghcr.io -u "$GITHUB_USER" --password-stdin

# Tag image for GHCR
echo ""
echo -e "${YELLOW}Tagging image...${NC}"
$CONTAINER_CMD tag "$LOCAL_IMAGE" "$GHCR_IMAGE:latest"

# Also tag with version if available
VERSION=$(date +%Y%m%d)
$CONTAINER_CMD tag "$LOCAL_IMAGE" "$GHCR_IMAGE:$VERSION"

# Push to GHCR
echo ""
echo -e "${YELLOW}Pushing to GitHub Container Registry...${NC}"
echo "This may take a while depending on your upload speed..."
echo ""

$CONTAINER_CMD push "$GHCR_IMAGE:latest"
$CONTAINER_CMD push "$GHCR_IMAGE:$VERSION"

echo ""
echo -e "${GREEN}======================================"
echo "         Push Complete!"
echo "======================================${NC}"
echo ""
echo "Image available at:"
echo -e "  ${BLUE}$GHCR_IMAGE:latest${NC}"
echo -e "  ${BLUE}$GHCR_IMAGE:$VERSION${NC}"
echo ""
echo -e "${YELLOW}Important:${NC} To make the package public:"
echo "  1. Go to https://github.com/users/Andrei9383/packages/container/blucast/settings"
echo "  2. Scroll to 'Danger Zone'"
echo "  3. Click 'Change visibility' → 'Public'"
echo ""
