"""Fail a demo smoke immediately if any sample tries to construct a boto3 client."""

import boto3


def refuse_boto3_client(*_args, **_kwargs):
    raise AssertionError("demo smoke attempted to construct a real boto3 client")


boto3.client = refuse_boto3_client
boto3.session.Session.client = refuse_boto3_client
