from pyln.testing.fixtures import *  # noqa: F401,F403
from pyln.client import RpcError
import os
import pytest
from pprint import pprint
import time


pluginopt = {'plugin': os.path.join(os.path.dirname(__file__), "paytest.py")}
EXPERIMENTAL_FEATURES = int(os.environ.get("EXPERIMENTAL_FEATURES", "0"))


def test_start(node_factory):
    node_factory.get_node(options=pluginopt)


def test_invoice(node_factory):
    l1 = node_factory.get_node(options=pluginopt)
    inv = l1.rpc.testinvoice('03' * 33)
    details = l1.rpc.decode(inv['invoice'])
    pprint(details)


def test_paytest_invoice(node_factory):
    """ l1 generates and pays an invoice on behalf of l2.
    """
    l1, l2 = node_factory.line_graph(2, opts=pluginopt, wait_for_announce=True)

    inv = l1.rpc.testinvoice(destination=l2.info['id'], amount=1)['invoice']
    details = l1.rpc.decode(inv)
    pprint(details)

    # Paying the invoice without the reinterpretation from paytest
    # will cause an unknown payment details directly.
    with pytest.raises(RpcError, match=r'WIRE_INCORRECT_OR_UNKNOWN_PAYMENT_DETAILS'):
        l1.rpc.pay(inv)


def test_simple_pay(node_factory):
    """ l1 send a payment that is going to be split.
    """

    # A successful probe should result in a failure message from pay:
    # {'code': 203,
    #  'message': 'failed: WIRE_INCORRECT_OR_UNKNOWN_PAYMENT_DETAILS (reply from remote)',
    #  'id': 1,
    #  'failcode': 16399,
    #  'failcodename': 'WIRE_INCORRECT_OR_UNKNOWN_PAYMENT_DETAILS',
    #  'bolt11': 'lnbcrt5m1p5849wcpp5424242424242424242424242424242424242424242424242424qrzjqgkjyd3q5dv6gllh77kygly9c3kfy0d9xwyjyxsq2nq3c83u5vw4jqqqqyqqqqgqqyqqqqqpqqqqqqgqpy9q9q9qsqdy923jhxapqd9h8vmmfvdjjqen0wgsrqv3jvseryvekxgcxzve489sngdmxvcmkvdmpvv6rgdmr8q6kxdpkvvunyvmyvy6nxvec8yeryvtpxqcr2drrxyckxvt9xd3kzve3vs6njsp54g6ac96nhj3l2rjfa08dyjj84j0fa0uxwh3htdcf6vlq7xw7r9cqwv8z2a0h7pte3glknnz6lvdzxkez7jgfh4kqsaz9ezgwzzty93rh02ru4lhhstxhp5rt6s26nef7pc5ljjgzrzuh0eugw6g96lt9tccqeeq6ln',
    #  'raw_message': '400f',
    #  'created_at': 1752864216,
    #  'destination': '026a04ab98d9e4774ad806e302dddeb63bea16b5cb5f223ee77478e861bb583eb3',
    #  'payment_hash': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    #  'status': 'failed',
    #  'amount_msat': 500000000,
    #  'amount_sent_msat': 0,
    #  'erring_index': 2,
    #  'erring_node': '026a04ab98d9e4774ad806e302dddeb63bea16b5cb5f223ee77478e861bb583eb3'}

    l1, l2 = node_factory.line_graph(2, opts=pluginopt, wait_for_announce=True)
    res = l1.rpc.paytest(l2.info['id'], 5 * 10**8)

    l2.daemon.wait_for_log(r'Received 500000000/500000000 with [0-9]+ parts')

    parts = res['status']['attempts']

    failures = [p['failure']['data'] for p in parts if 'failure' in p and 'data' in p['failure']]
    pprint(failures)

    outcomes = [f['failcode'] for f in failures]
    is16399 = [p == 16399 for p in outcomes]
    assert all(is16399)
    assert len(is16399) >= 1

    # The erring node should be the fake node included in the invoice, not l2.
    erring_nodes = [e['erring_node'] for e in failures]
    for erring_node in erring_nodes:
        assert erring_node == '026a04ab98d9e4774ad806e302dddeb63bea16b5cb5f223ee77478e861bb583eb3'


def test_mpp_pay(node_factory, bitcoind):
    """ l1 send a payment that is going to be split.
    """
    l1, l2, l3, l4 = node_factory.get_nodes(4, opts=pluginopt)

    # Two routes to l4: one via l2, and one via l3.
    l1.rpc.connect(l2.info['id'], 'localhost', l2.port)
    l1.fundchannel(l2, 100000)
    l1.rpc.connect(l3.info['id'], 'localhost', l3.port)
    l1.fundchannel(l3, 100000)
    l2.rpc.connect(l4.info['id'], 'localhost', l4.port)
    scid24, _ = l2.fundchannel(l4, 100000)
    l3.rpc.connect(l4.info['id'], 'localhost', l4.port)
    scid34, _ = l3.fundchannel(l4, 100000)
    #mine_funding_to_announce(bitcoind, [l1, l2, l3, l4])
    bitcoind.generate_block(6, 0)

    # Wait until l1 knows about all channels.
    while len(l1.rpc.listchannels()['channels']) != 8:
        time.sleep(0.5)

    res = l1.rpc.paytest(l4.info['id'], 120 * 10**6)

    l4.daemon.wait_for_log(r'Received 120000000/120000000 with [0-9]+ parts')

    parts = res['status']['attempts']
    # We no longer autosplit when we have a direct channel
    # assert len(parts) > 1  # Initial split + >1 part

    failures = [p['failure']['data'] for p in parts if 'failure' in p and 'data' in p['failure']]
    pprint(failures)

    outcomes = [f['failcode'] for f in failures]
    is16399 = [p == 16399 for p in outcomes]
    assert all(is16399)
    assert len(is16399) >= 1


def test_incoming_payment(node_factory):
    """Ensure that we don't fail if the payment is not a paytest.
    """
    l1, l2 = node_factory.line_graph(2, opts=pluginopt, wait_for_announce=True)
    inv = l2.rpc.invoice(42, 'lbl', 'desc')['bolt11']
    l1.rpc.pay(inv)

    plugins = l2.rpc.listconfigs()['configs']['plugin']['values_str']
    plugin_with_path = os.path.join(os.path.dirname(__file__), "paytest.py")
    assert plugin_with_path in plugins

    plugins = l1.rpc.listconfigs()['configs']['plugin']['values_str']
    assert plugin_with_path in plugins
