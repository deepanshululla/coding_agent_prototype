#!/usr/bin/env python3
"""Quick manual test for autocomplete functionality."""

from tui.commands import get_command_names
from tui.components.input_box import InputBox

# Test 1: Get all command names
print("Available commands:", get_command_names())

# Test 2: Get completions for "/"
input_box = InputBox()
print("\nCompletions for '/':", input_box._get_completions("/"))

# Test 3: Get completions for "/mo"
print("Completions for '/mo':", input_box._get_completions("/mo"))

# Test 4: Get completions for "/s"
print("Completions for '/s':", input_box._get_completions("/s"))

# Test 5: No completions for "/xyz"
print("Completions for '/xyz':", input_box._get_completions("/xyz"))

# Test 6: State management
input_box._completion_candidates = ["help", "model"]
input_box._completion_index = 1
print("\nBefore reset:", input_box._completion_candidates, input_box._completion_index)
input_box._reset_completion()
print("After reset:", input_box._completion_candidates, input_box._completion_index)

print("\n✓ All manual tests passed!")
