#!/bin/bash
#
# LLM Code Review - Installation Script
#
# Usage:
#   ./install.sh              # Install locally only
#   ./install.sh --global     # Install + add global 'llm-code-review' command
#   ./install.sh --hook       # Install + set up git hook in current repo
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
GLOBAL_CMD="/usr/local/bin/llm-code-review"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check Python
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        print_error "Python not found. Please install Python 3.8+"
        exit 1
    fi

    # Check version
    PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    print_success "Found Python $PYTHON_VERSION"
}

# Create virtual environment
setup_venv() {
    print_step "Setting up virtual environment..."

    if [ -d "$VENV_DIR" ]; then
        print_warning "Virtual environment already exists, skipping..."
    else
        $PYTHON_CMD -m venv "$VENV_DIR"
        print_success "Created virtual environment at $VENV_DIR"
    fi

    # Activate and install dependencies
    source "$VENV_DIR/bin/activate"
    pip install --quiet --upgrade pip
    pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
    print_success "Installed dependencies"
}

# Setup configuration
setup_config() {
    print_step "Setting up configuration..."

    if [ -f "$SCRIPT_DIR/review_config.json" ]; then
        print_warning "review_config.json already exists, skipping..."
    else
        cp "$SCRIPT_DIR/review_config_example.json" "$SCRIPT_DIR/review_config.json"
        print_success "Created review_config.json from example"
    fi
}

# Install global command
install_global() {
    print_step "Installing global command..."

    # Create wrapper script
    WRAPPER_CONTENT="#!/bin/bash
# LLM Code Review - Global wrapper
# Installed from: $SCRIPT_DIR

source \"$VENV_DIR/bin/activate\"
python \"$SCRIPT_DIR/review.py\" \"\$@\"
"

    if [ -w "/usr/local/bin" ]; then
        echo "$WRAPPER_CONTENT" > "$GLOBAL_CMD"
        chmod +x "$GLOBAL_CMD"
        print_success "Installed global command: llm-code-review"
    else
        print_warning "Need sudo to install to /usr/local/bin"
        echo "$WRAPPER_CONTENT" | sudo tee "$GLOBAL_CMD" > /dev/null
        sudo chmod +x "$GLOBAL_CMD"
        print_success "Installed global command: llm-code-review"
    fi
}

# Install git hook in target repository
install_hook() {
    local target_dir="${1:-$(pwd)}"

    print_step "Installing git hook..."

    if [ ! -d "$target_dir/.git" ]; then
        print_error "Not a git repository: $target_dir"
        exit 1
    fi

    local hook_file="$target_dir/.git/hooks/pre-commit"

    # Backup existing hook
    if [ -f "$hook_file" ]; then
        cp "$hook_file" "$hook_file.backup"
        print_warning "Backed up existing pre-commit hook"
    fi

    cat > "$hook_file" << EOF
#!/bin/bash
# LLM Code Review - Pre-commit hook
# Installed from: $SCRIPT_DIR

source "$VENV_DIR/bin/activate"
python "$SCRIPT_DIR/review.py" --mode staged

exit_code=\$?
if [ \$exit_code -eq 1 ]; then
    echo ""
    echo "Commit blocked due to critical issues."
    echo "Fix the issues above or use 'git commit --no-verify' to skip."
    exit 1
fi

exit 0
EOF

    chmod +x "$hook_file"
    print_success "Installed pre-commit hook in $target_dir"
}

# Print usage instructions
print_usage() {
    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo "Before using, set your API key:"
    echo ""
    echo "  export LLM_API_KEY=\"your-api-key\""
    echo ""
    echo "Optional - override model/endpoint:"
    echo ""
    echo "  export LLM_BASE_URL=\"https://api.openai.com/v1\""
    echo "  export LLM_MODEL=\"gpt-4\""
    echo ""

    if [ "$INSTALL_GLOBAL" = true ]; then
        echo "Usage (global command):"
        echo ""
        echo "  llm-code-review --mode staged     # Review staged changes"
        echo "  llm-code-review --mode all        # Review all changes"
        echo "  llm-code-review --test-connection # Test API connection"
        echo ""
    else
        echo "Usage (from this directory):"
        echo ""
        echo "  source $VENV_DIR/bin/activate"
        echo "  python review.py --mode staged"
        echo ""
        echo "To install global command, run:"
        echo ""
        echo "  ./install.sh --global"
        echo ""
    fi

    if [ "$INSTALL_HOOK" = true ]; then
        echo "Git hook installed - reviews will run automatically before commits."
        echo ""
    else
        echo "To add pre-commit hook to a repository:"
        echo ""
        echo "  cd /path/to/your/repo"
        echo "  $SCRIPT_DIR/install.sh --hook"
        echo ""
    fi
}

# Parse arguments
INSTALL_GLOBAL=false
INSTALL_HOOK=false

for arg in "$@"; do
    case $arg in
        --global)
            INSTALL_GLOBAL=true
            ;;
        --hook)
            INSTALL_HOOK=true
            ;;
        --help|-h)
            echo "LLM Code Review - Installation Script"
            echo ""
            echo "Usage:"
            echo "  ./install.sh              Install locally"
            echo "  ./install.sh --global     Install + global 'llm-code-review' command"
            echo "  ./install.sh --hook       Install + git pre-commit hook"
            echo "  ./install.sh --global --hook   All of the above"
            echo ""
            exit 0
            ;;
        *)
            print_error "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# Main installation
echo ""
echo "LLM Code Review - Installation"
echo "=============================="
echo ""

check_python
setup_venv
setup_config

if [ "$INSTALL_GLOBAL" = true ]; then
    install_global
fi

if [ "$INSTALL_HOOK" = true ]; then
    install_hook "$(pwd)"
fi

print_usage
