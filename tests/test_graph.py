import pytest
from unittest.mock import AsyncMock, patch
from langgraph.types import Command, interrupt
import aiosqlite

from graph.state import AgentState
from graph.graph import build_graph, _route_after_supervisor, _should_send
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def test_supervisor_routing_logic():
    state_cross_sell: AgentState = {
        'customer_id': '919876543210',
        'draft_id': 'test-1',
        'agents_to_call': ['cross_sell_agent'],
    }
    assert _route_after_supervisor(state_cross_sell) == 'cross_sell_node'

    state_direct_reply: AgentState = {
        'customer_id': '919876543210',
        'draft_id': 'test-2',
        'agents_to_call': ['direct_reply'],
    }
    assert _route_after_supervisor(state_direct_reply) == 'direct_reply_node'


def test_should_send_logic():
    state_ok: AgentState = {
        'customer_id': '919876543210',
        'draft_id': 'test-1',
        'error': None,
    }
    assert _should_send(state_ok) == 'send_node'

    state_rejected: AgentState = {
        'customer_id': '919876543210',
        'draft_id': 'test-2',
        'error': 'Draft rejected by human reviewer',
    }
    assert _should_send(state_rejected) == '__end__'


@pytest.mark.asyncio
async def test_full_graph_interrupt_and_resume():
    conn = await aiosqlite.connect(':memory:')
    saver = AsyncSqliteSaver(conn)
    await saver.setup()

    draft_id = 'test-draft-uuid'
    config = {'configurable': {'thread_id': draft_id}}

    mock_load = AsyncMock(return_value={
        'customer_name': 'Ramesh',
        'conversation_events': [{'text': 'Need cutting wheels', 'direction': 'incoming'}],
        'purchased_products': ['FG000066'],
        'last_purchased_product': 'FG000066',
    })

    mock_parser = AsyncMock(return_value={
        'customer_intent': 'purchase_signal',
        'purchase_signals': True,
        'sentiment': 'positive',
        'mentioned_products': [{'product_id': 'FG000066', 'product_name': 'E6013'}],
        'cross_sell_recommendations': [{'product_id': 'FG000523', 'product_name': 'Cut-off wheel'}],
        'conversation_summary': 'Customer needs cutting wheels',
    })

    mock_supervisor = AsyncMock(return_value={'agents_to_call': ['cross_sell_agent']})
    mock_cross_sell = AsyncMock(return_value={'agent_output': '{\"template_key\": \"cross_sell_only\"}'})
    mock_fill = AsyncMock(return_value={'generated_message': 'Special offer on Cut-off wheels!'})

    async def mock_save_draft_with_interrupt(state: AgentState):
        decision = interrupt({
            'draft_id': state['draft_id'],
            'customer_id': state['customer_id'],
            'preview': state.get('generated_message', ''),
        })
        if decision.get('action') == 'approve':
            return {'generated_message': state.get('generated_message', '')}
        return {'error': 'rejected'}

    mock_send = AsyncMock(return_value={})

    with (
        patch('graph.graph.load_customer_data_node', new=mock_load),
        patch('graph.graph.parser_node', new=mock_parser),
        patch('graph.graph.supervisor_node', new=mock_supervisor),
        patch('graph.graph.cross_sell_node', new=mock_cross_sell),
        patch('graph.graph.message_fill_node', new=mock_fill),
        patch('graph.graph.save_draft_node', new=mock_save_draft_with_interrupt),
        patch('graph.graph.send_node', new=mock_send),
    ):
        graph = build_graph(saver)

        # 1. Run graph — must pause at interrupt
        await graph.ainvoke({
            'customer_id': '919876543210',
            'draft_id': draft_id,
        }, config=config)

        # Verify graph is paused at interrupt
        state = await graph.aget_state(config)
        assert len(state.tasks) > 0
        assert len(state.tasks[0].interrupts) > 0
        int_data = state.tasks[0].interrupts[0].value
        assert int_data['draft_id'] == draft_id
        assert int_data['preview'] == 'Special offer on Cut-off wheels!'

        # 2. Resume with Human Approval Command
        await graph.ainvoke(Command(resume={'action': 'approve'}), config=config)

        # Verify send_node was called and graph completed
        mock_send.assert_awaited_once()
        final_state = await graph.aget_state(config)
        assert len(final_state.tasks) == 0

    await conn.close()
