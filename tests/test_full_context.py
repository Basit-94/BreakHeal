"""Unit tests verifying full-context extraction and OOP awareness across Python, TypeScript, and Java."""

import tempfile
from pathlib import Path
from breakheal.context import extract_context, scan_directory_for_functions
from breakheal.ts_context import extract_ts_context, extract_ts_types_and_interfaces
from breakheal.java_context import extract_java_context


def test_python_full_context_oop_extraction():
    sample_py = """import math
from typing import List, Optional

class PaymentProcessor:
    \"\"\"Service managing customer payments.\"\"\"
    def __init__(self, api_key: str, timeout_sec: int = 30):
        self.api_key = api_key
        self.timeout = timeout_sec

    def process_charge(self, amount: float, currency: str = "USD") -> bool:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return True

    @staticmethod
    def format_currency(amount: float) -> str:
        return f"${amount:.2f}"
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(sample_py)
        temp_file = Path(f.name)

    try:
        # Test instance method
        ctx = extract_context(temp_file, target_name="PaymentProcessor.process_charge")
        assert ctx.target_name == "process_charge"
        assert ctx.is_method is True
        assert ctx.class_name == "PaymentProcessor"
        assert ctx.is_static is False
        assert ctx.constructor_code is not None
        assert "__init__" in ctx.constructor_code
        assert "PaymentProcessor" in (ctx.class_context or "")
        assert sample_py == ctx.full_source

        # Test static method
        ctx_static = extract_context(temp_file, target_name="format_currency")
        assert ctx_static.target_name == "format_currency"
        assert ctx_static.is_method is True
        assert ctx_static.is_static is True
        assert ctx_static.class_name == "PaymentProcessor"
    finally:
        temp_file.unlink()


def test_typescript_full_context_and_types_extraction():
    sample_ts = """import { Client } from './client.js';

export interface UserAccount {
    id: string;
    tier: 'basic' | 'pro' | 'enterprise';
    balance: number;
}

export type CurrencyCode = 'USD' | 'EUR' | 'GBP';

export class BillingEngine {
    private client: Client;

    constructor(client: Client, private defaultCurrency: CurrencyCode = 'USD') {
        this.client = client;
    }

    public calculateInvoice(items: number[]): number {
        return items.reduce((acc, curr) => acc + curr, 0);
    }
}
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".ts", delete=False, encoding="utf-8") as f:
        f.write(sample_ts)
        temp_file = Path(f.name)

    try:
        types = extract_ts_types_and_interfaces(sample_ts)
        assert any("UserAccount" in t for t in types)
        assert any("CurrencyCode" in t for t in types)

        ctx = extract_ts_context(temp_file, target_name="BillingEngine.calculateInvoice")
        assert ctx.class_name == "BillingEngine"
        assert ctx.target_name == "BillingEngine.calculateInvoice"
        assert ctx.is_static is False
        assert ctx.constructor_code is not None
        assert "constructor" in ctx.constructor_code
        assert ctx.full_source == sample_ts
        assert ctx.types_and_interfaces is not None
        assert len(ctx.types_and_interfaces) >= 2
    finally:
        temp_file.unlink()


def test_java_full_context_constructor_and_fields_extraction():
    sample_java = """package com.example.service;

import java.util.Map;
import java.util.HashMap;

public class OrderService {
    private final Map<String, Double> rates = new HashMap<>();
    private int maxRetries = 3;

    public OrderService(Map<String, Double> initialRates) {
        if (initialRates != null) {
            this.rates.putAll(initialRates);
        }
    }

    public double calculateTotal(double subtotal, double taxRate) {
        return subtotal + (subtotal * taxRate);
    }

    public static String getVersion() {
        return "1.0.0";
    }
}
"""
    with tempfile.NamedTemporaryFile("w+", suffix=".java", delete=False, encoding="utf-8") as f:
        f.write(sample_java)
        temp_file = Path(f.name)

    try:
        ctx = extract_java_context(temp_file, target_name="calculateTotal")
        assert ctx.class_name == "OrderService"
        assert ctx.method_name == "calculateTotal"
        assert ctx.is_static is False
        assert ctx.constructor_code is not None
        assert "OrderService(Map<String, Double> initialRates)" in ctx.constructor_code
        assert ctx.fields_code is not None
        assert "rates" in ctx.fields_code
        assert ctx.full_source == sample_java

        ctx_static = extract_java_context(temp_file, target_name="getVersion")
        assert ctx_static.is_static is True
    finally:
        temp_file.unlink()
