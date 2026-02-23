#!/usr/bin/env python3
"""
Extracts just the email reply from the ais_email_and_context
"""

import yaml

def transform(text: str) -> str:
    data = yaml.load(text, Loader=yaml.FullLoader)
    return data['response']
