from telethon import TelegramClient, events
import re
import MetaTrader5 as mt5

# Initialize Telegram API credentials
api_id = 'xxxxxxx'  # Your API ID
api_hash = 'xxxxxxxxxxxx'  # Your API hash

client = TelegramClient('session_name', api_id, api_hash)

mt5.initialize()

signal_info = {
    "Gold": None,
    "Main_Action": None,
    "Main_Price": None,
    "Limit_Action": None,
    "Limit_Price": None,
    "SL": None,
    "TP": None
}

async def find_private_channel(client, channel_name):
    my_private_channel_id = None

    async for dialog in client.iter_dialogs():
        if dialog.name == channel_name:
            my_private_channel_id = dialog.id
            break

    if my_private_channel_id is None:
        print("Channel not found.")
    else:
        print(f"Channel ID is: {my_private_channel_id}")
    return my_private_channel_id

def process_message(message_text):
    main_signal_match = re.search(r'GOLD\s+(BUY LIMIT|SELL LIMIT|BUY|SELL)\s+@\s*(\d+\.?\d*)', message_text, re.IGNORECASE)
    limit_signal_match = re.search(r'SECOND\s+(BUY|SELL)\s+LIMIT\s+@\s*(\d+\.?\d*)', message_text, re.IGNORECASE)

    if main_signal_match:
        action = main_signal_match.group(1).upper()
        price = float(main_signal_match.group(2))
        signal_info["Gold"] = "Gold"
        signal_info["Main_Action"] = action
        signal_info["Main_Price"] = price

        sl_match = re.search(r'SL\s*@\s*(\d+\.?\d*)', message_text, re.IGNORECASE)
        tp_match = re.search(r'TP\s*@\s*(\d+\.?\d*)', message_text, re.IGNORECASE)

        if sl_match:
            signal_info["SL"] = float(sl_match.group(1))

        if tp_match:
            signal_info["TP"] = float(tp_match.group(1))

        current_price = mt5.symbol_info_tick("XAUUSD.m").ask if action == "BUY" else mt5.symbol_info_tick("XAUUSD.m").bid
        if "LIMIT" in action or (action == "BUY" and current_price > price) or (action == "SELL" and current_price < price):

            execute_order(action + " LIMIT", price, signal_info["SL"], signal_info["TP"])
        else:
            execute_order(action, current_price, signal_info["SL"], signal_info["TP"])

    if limit_signal_match:
        action = limit_signal_match.group(1).upper() + " LIMIT"  
        price = float(limit_signal_match.group(2))
        signal_info["Limit_Action"] = action
        signal_info["Limit_Price"] = price

        execute_order(signal_info["Limit_Action"], signal_info["Limit_Price"], signal_info["SL"], signal_info["TP"])

    if "MOVE SL AT BREAKEVEN" in message_text:
        move_sl_to_breakeven()

def execute_order(action, price, sl, tp):
    symbol = "XAUUSD.m"  # Symbol name on MT5, depends on broker
    lot_size = 0.1  # Lot size for orders

    current_price = mt5.symbol_info_tick(symbol).ask if action.startswith("BUY") else mt5.symbol_info_tick(symbol).bid
    is_limit_order = "LIMIT" in action

    order_type = {
        "BUY": mt5.ORDER_TYPE_BUY,
        "SELL": mt5.ORDER_TYPE_SELL,
        "BUY LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL LIMIT": mt5.ORDER_TYPE_SELL_LIMIT
    }.get(action, None)

    if order_type is None:
        print(f"Error: Invalid order type '{action}'")
        return

    request = {
        "action": mt5.TRADE_ACTION_DEAL if not is_limit_order else mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price if is_limit_order else current_price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 234000,
        "comment": f"{order_type} order for {symbol}",
        "type_time": mt5.ORDER_TIME_GTC
    }

    for filling_mode in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
        request["type_filling"] = filling_mode
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"Order successfully placed with {filling_mode}: {action} at {price}, SL: {sl}, TP: {tp}")
            break
        else:
            print(f"Attempt with filling mode {filling_mode} failed, retcode={result.retcode if result else 'No response'}. Comment: {result.comment if result else 'No comment'}")

def move_sl_to_breakeven():
    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        print("No open positions to move SL.")
        return

    for position in positions:
        entry_price = position.price_open
        symbol = position.symbol

        sl = entry_price

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": position.ticket,
            "sl": sl
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"SL moved to breakeven for position {position.ticket}: {sl}")
        else:
            print(f"Failed to move SL for position {position.ticket}, retcode={result.retcode if result else 'No response'}. Comment: {result.comment if result else 'No comment'}")

    cancel_all_limit_orders()

def cancel_all_limit_orders():
    orders = mt5.orders_get()
    if orders is None:
        print(f"Failed to get orders, error code: {mt5.last_error()}")
        return

    for order in orders:
        if order.type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT):
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"Failed to cancel order {order.ticket}, error: {result.comment}")
            else:
                print(f"Canceled limit order {order.ticket} successfully.")

@client.on(events.NewMessage)  
async def new_message_handler(event):
    if event.chat_id == target_channel_id:
        message_text = event.message.message
        print("New message received:", message_text)
        print("-" * 40)
        process_message(message_text)

@client.on(events.MessageEdited) 
async def edited_message_handler(event):
    if event.chat_id == target_channel_id:
        message_text = event.message.message
        print("Message edited:", message_text)
        print("-" * 40)
        process_message(message_text)

async def main():
    channel_name = "xxxxxxxxxx"  # Replace with your channel name
    global target_channel_id  
    target_channel_id = await find_private_channel(client, channel_name)

    if target_channel_id:
        print(f"Listening for new and edited messages in channel ID: {target_channel_id}")
        await client.run_until_disconnected()  

with client:
    client.loop.run_until_complete(main())
