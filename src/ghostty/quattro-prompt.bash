# Quattro Ghostty prompt. Shell builtins only; no commands run at each prompt.
# Sourced by Bash only in an interactive Ghostty shell. Other shells keep theirs.
if [[ $- == *i* && ${TERM_PROGRAM-} == ghostty ]]; then
    PS1='\[\e[90m\]┌─\[\e[0m\] \u@\h  \w\n\[\e[90m\]└─\[\e[0m\] \$ '
fi
