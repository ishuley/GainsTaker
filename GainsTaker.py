# this is my first actually useful program. my gratitude to nick winn, pyslackers chat room, /r/learnpython,
# learnprogramming.academy, real python, and others for helping me get this far!

import requests
import json
import time
import hmac
import hashlib
import decimal
from decimal import Decimal
from typing import Tuple

decimal.getcontext().prec = 100
decimal_zero = Decimal()


# buy/bid and sell/ask always refers to the quote asset (the first asset) (ex: ARDRETH : buy ARDR or sell ARDR)
# the second asset is the 'base' asset (ex: ETH is base asset in ARDRETH)
# except in get_pairing_price, side of buy always refers to quote asset, side of sell always refers to base
# examples in comments above the functions


class Exchange(object):

    # for functions that should be applicable to every exchange. I imagine most exchange APIs don't work
    # the same way, so most functions will be part of subclasses tailored to each exchange

    def __init__(self, api_token: str = None, api_token_secret: str = None):
        self.api_token = api_token
        self.api_token_secret = api_token_secret

    def get_signature(self, query_string: str) -> str:
        # signing the param_strings used to interact with the exchange APIs should be the same everywhere
        undigested_sig = hmac.new(self.api_token_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256)
        return undigested_sig.hexdigest()

    # get_tax_due() will need to be formatted at some point to however the specific exchange needs its values formatted
    # my take is to implement that in a get_tax_due() function in the subclass that
    # returns a formatted super().get_class_due()
    @staticmethod
    def get_tax_due(spend_total_usd: Decimal, cost_basis_usd: Decimal = None, term: str = 'short')\
            -> Decimal or str:
        term = term.lower()
        if term != 'short' and term != 'long':
            invalid_term = list()
            invalid_term.append(term)
            return tuple(invalid_term)
        if cost_basis_usd is None:
            cost_basis_usd = decimal_zero
        tax_due_usd = decimal_zero
        based_total = spend_total_usd - cost_basis_usd
        if term == 'short':
            tax_due_usd = based_total * Decimal('0.3')
        elif term == 'long':
            tax_due_usd = based_total * Decimal('0.16')
        return tax_due_usd


class Binance(Exchange):
    # https://github.com/binance-exchange/binance-official-api-docs/blob/master/rest-api.md

    def __init__(self, api_token: str = None, api_token_secret: str = None):
        super().__init__(api_token, api_token_secret)
        self.API_URL = 'https://api.binance.com/api/'
        self.headers = {
            'X-MBX-APIKEY': self.api_token
        }

    # takes a Decimal and returns it with 6 decimal places, rounded up or down depending on round_direction
    # round_direction: ROUND_DOWN, ROUND_UP
    @staticmethod
    def format_a_decimal(dec: Decimal, round_direction: str = 'ROUND_DOWN',
                         lot_size: Decimal = Decimal('.00000001')) -> Decimal:
        return Decimal(dec.quantize(Decimal(lot_size), rounding=round_direction))

    # Binance gets its own get_tax_due() because it only works with up to 6 decimal places, so it needs
    # to be formatted as such
    def get_tax_due(self, spend_total_usd: Decimal, cost_basis_usd: Decimal = None, term: str = 'short') \
            -> Decimal or str:
        return self.format_a_decimal(super().get_tax_due(spend_total_usd, cost_basis_usd, term), 'ROUND_UP')

    # The following functions work with information from Binance using the following formats:

    #   Examples:
    #       pairing: 'USDCBTC'
    #       side: 'buy' or 'sell'
    #       qty: decimal.Decimal('4.513')
    #       symbol: 'ETH'
    #       pairing_side: 'quote' or 'base'

    # BTCUSDC; buy : send a USDC value (get back BTC), sell : send a BTC value (get back USDC)
    def get_pairing_price(self, pairing: str, side: str = 'buy', qty: Decimal = decimal_zero) -> tuple:
        side = side.lower()
        pairing = pairing.upper()
        input_check = self._input_check(pairing, side, qty)
        if input_check is not True:  # _input_check() either returns True, or a tuple containing applicable error ids
            # so 'if not input_check' doesn't work because that's expecting a False it'll never get
            # I do this in many spots throughout the program
            return input_check
        else:
            if pairing == 'USDCBTC':  # oddly, USDCBTC returns as a valid pairing, but the only valid market is BTCUSDC
                pairing = 'BTCUSDC'
                if side == 'sell':
                    side = 'buy'
                else:
                    side = 'sell'
            if side == 'buy':  # determines which side of the orderbook to use
                book = 'bids'
            else:
                book = 'asks'
            api_url = self.API_URL + "v1/depth"
            orders = requests.get(api_url, params={'symbol': pairing, 'limit': 1000})
            orders_json = json.loads(orders.text)
            order_book = orders_json[book]  # so now we have an iterable list of orders to estimate a price with
            qty_counter = decimal_zero
            price = decimal_zero
            buy_asset = None
            buy_asset_qty = None
            symbol1, symbol2 = self._split_a_pairing(pairing, ret_valid_pairing=True)
            for order in order_book:  # determines how much we'll have to pay using orderbook information
                #  see binance's api documentation for more details
                if 'USDC' in pairing:
                    if qty_counter + Decimal(order[0]) >= qty:
                        price = Decimal(order[0])
                        break
                    else:
                        qty_counter += Decimal(order[0])
                else:
                    if qty_counter + Decimal(order[1]) >= qty:
                        price = Decimal(order[0])
                        break
                    else:
                        qty_counter += Decimal(order[1])
            if book == 'asks':
                buy_asset_qty = qty / price
                buy_asset = symbol1
            elif book == 'bids':
                buy_asset_qty = qty * price
                buy_asset = symbol2
            return self.format_a_decimal(buy_asset_qty), buy_asset

    # get_price_usdc() is like a get_pairing_price(), except it is exclusively USDC, and if a pairing
    # doesn't exist, it uses BTC as a go between and returns the appropriate values as though it did
    # so now we can get a USDC price for every asset available on Binance
    def get_price_usdc(self, symbol: str, qty: Decimal = decimal_zero, side: str = 'buy') -> Tuple[Decimal, str] or str:
        symbol = symbol.upper()
        side = side.lower()
        input_check = self._input_check(None, side, qty, symbol)
        if input_check is not True:
            return input_check
        else:
            if symbol == 'USDC':  # asking for the price of usdc in usdc lol
                return self.format_a_decimal(qty), 'USDC'
            elif symbol == 'BTC':  # as explained in these comments, this pairing doesn't work in get_pairing_price()
                # i think it's because binance's BTC tickers don't follow their other patterns
                if side == 'buy':
                    other_side = 'sell'
                else:
                    other_side = 'buy'
                return self.get_pairing_price('USDCBTC', other_side, qty)
            pairing_path = self._get_pairing_path_to_usdc(symbol)  # figures out the quickest path to USDC
            pairing_path_length = len(pairing_path)  # tells us whether we're using BTC as a go between
            # tuple contains two pairings if we are
            if pairing_path_length == 1:  # if not
                return self.get_pairing_price(pairing=pairing_path[0], side=side, qty=qty)
            elif pairing_path_length == 2:  # if so
                other_qty = self.get_pairing_price(pairing_path[0], side=side, qty=qty)
                if other_qty[1] == 'BTC':
                    ret_symbol = 'USDC'
                else:
                    ret_symbol = symbol
                return self.get_pairing_price(pairing=pairing_path[1], side=side, qty=other_qty[0])[0], ret_symbol
                # format_a_decimal() happens in get_pairing_price(), so no need to do that here

    # I'm going to include the option to use your entire remaining balance of an asset in a trade,
    # get_single_balance() will fetch that balance
    # I also ended up using this in execute_trade() to deduce the balance of new crypto after the transaction,
    # since I'm not seeing a way to do this through the API itself
    def get_single_balance(self, symbol: str) -> Tuple[Decimal, str] or str:
        symbol = symbol.upper()
        input_check = self._input_check(None, None, None, symbol)
        if input_check is not True:
            return input_check
        else:
            query_string = 'timestamp=' + str(int(time.time()) * 1000)
            sig = self.get_signature(query_string)
            balances = requests.get(self.API_URL + 'v3/account?' +
                                    query_string + '&signature=' + sig, headers=self.headers)
            response = json.loads(balances.text)
            balance_list = response['balances']
            for asset_dict in balance_list:
                if asset_dict['asset'] == symbol:
                    return self.format_a_decimal(Decimal(asset_dict['free'])), symbol

    # make the tax trade(s) before the main trade's function gets called
    # figures out the necessary trades to convert the given asset to the USDC amount given
    # then executes those trades using execute_trade()
    def execute_tax_trade(self, tax_due_usd: Decimal, asset_being_sold: str):
        usdc_path = self._get_pairing_path_to_usdc(asset_being_sold)  # so we know HOW to buy USDC

        if len(usdc_path) == 1:  # we have a direct pairing with USDC available
            pairing = self.get_valid_pairing('USDC', asset_being_sold)  # figure out how to buy USDC in a valid pairing
            # acquire USDC using execute_trade(), return how much was actually bought with Binance's response
            return self.execute_trade(pairing[0], pairing[3], tax_due_usd)

        # while relying on BTC as a bridge, len(usdc_path) will always be 2 here
        btc_pairing = self.get_valid_pairing(asset_being_sold, 'BTC')  # figure out how to buy BTC

        # acquire BTC with execute_trade(), assign how much was actually bought to a variable
        btc_received = self.execute_trade(btc_pairing[0], btc_pairing[3], tax_due_usd)[0]
        return self.execute_trade('BTCUSDC', 'sell', btc_received)
        # format_a_decimal() isn't necessary in either of these conditionals because execute_trade() calls it
        # before returning

    # execute_trade() actually executes the trade
    def execute_trade(self, pairing: str, side: str, qty) -> tuple:
        # input checks and formatting
        pairing = pairing.upper()
        side = side.upper()
        if side == 'BID':
            side = 'BUY'
        if side == 'ASK':
            side = 'SELL'
        qty = self.format_a_decimal(qty)
        qty = str(qty)

        # split the pairing, determine the balance of the asset being gained,
        # store the balance compare with new balance after the order is executed
        # so it can be returned, I don't see a way to do this through Binance API
        # an alternative approach might've been to use newOrderRespType=FULL below, and
        # derive it from the 'fills' values, but this seemed easier
        quote_asset, base_asset = self._split_a_pairing(pairing)
        if side == 'BUY':
            asset_to_use = quote_asset
        else:
            asset_to_use = base_asset
        bal_before_acquiring = self.get_single_balance(asset_to_use)

        # construct the query_string and signature
        symbol = 'symbol=' + pairing + '&'
        side = 'side=' + side + '&'
        type_ = 'type=' + 'MARKET&'  # TODO implement limit orders someday maybe
        quantity = 'quantity=' + qty + '&'
        new_order_resp_type = 'newOrderRespType=RESULT&'
        timestamp = 'timestamp=' + str(int(time.time()) * 1000)
        query_string = symbol + side + type_ + quantity + new_order_resp_type + timestamp
        sig = self.get_signature(query_string)

        # POST the order
        order = requests.post(self.API_URL + 'v3/order?' + query_string + '&signature=' + sig, headers=self.headers)

        # parse and return results
        result = json.loads(order.text)
        bal_after_acquiring = self.get_single_balance(asset_to_use)  # returns a Decimal
        amt_of_asset_acquired = Decimal(bal_after_acquiring[0]) - Decimal(bal_before_acquiring[0])
        # these are only casted as Decimal to humor my IDE ^
        amt_of_asset_acquired = self.format_a_decimal(amt_of_asset_acquired)
        return amt_of_asset_acquired, asset_to_use, result
        # returns a tuple: (Decimal containing amount acquired, asset acquired, binance's response to POST)
    # this should work, but I haven't tested it yet because that requires me sending money to binance
    # which i'll do soon. - sending a POST to v3/order/test seems to not return a dictionary value for order,
    # i'm thinking because the order doesn't get placed,
    # but I'm getting status_code 200 so all seems to be working, we'll give it a whirl without /test

    # get_pairing_list() returns a tuple of possible pairings available on binance
    # oddly, USDCBTC returns as a valid pairing, when it is not, resulting in changes to several of
    # this class' functions
    def get_pairing_list(self) -> tuple:
        symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
        symbols_json = json.loads(symbols_string.text)
        return_list = []
        for item in symbols_json['symbols']:
            return_list.append(item['symbol'])
        return tuple(return_list)

    # _get_asset_symbols() returns a tuple of asset symbols
    # pairing_side:'quote' produces a list of symbols that are the first part of a pairing
    # pairing_side:'base' produces a list of symbols that are in the second part (all of them,
    # in one pairing or another. use 'base' to generate a list of every asset binance handles
    def _get_asset_symbols(self, pairing_side: str) -> tuple:
        pairing_side = pairing_side.lower()
        input_check = self._input_check(None, None, None, None, pairing_side)
        if input_check is not True:
            return input_check
        else:
            symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
            symbols_json = json.loads(symbols_string.text)
            assets_set = set()
            for item in symbols_json['symbols']:
                assets_set.add(item[pairing_side + 'Asset'])  # add each asset to a set to remove duplicates
            return tuple(assets_set)

    # get_valid_pairing() returns a tuple for a valid pairing if one exists for the given assets
    # it returns the side assuming you want to acquire the first symbol in the parameters
    # so if the asset sides (quote, base) had to be switched for a valid pairing, it also switches the side
    # (ex: ARDRETH only exists but you send ETH as quote asset and ARDR as base), then it returns sell instead of buy
    def get_valid_pairing(self, quote_asset: str, base_asset: str) -> Tuple[str, str, str, str] or tuple:

        base_asset, quote_asset = base_asset.upper(), quote_asset.upper()

        input_check_q = self._input_check(None, None, None, quote_asset, None)
        input_check_b = self._input_check(None, None, None, base_asset, None)
        input_check_pqb = self._input_check(quote_asset + base_asset)
        input_check_pbq = self._input_check(base_asset + quote_asset)

        if input_check_b is not True:
            return input_check_b
        if input_check_q is not True:
            return input_check_q
        if input_check_pqb is not True and input_check_pbq is not True:
            return input_check_pqb

        if input_check_pqb is True:
            return quote_asset + base_asset, \
                   quote_asset, \
                   base_asset, \
                   'buy'
        elif input_check_pbq is True:
            return base_asset + quote_asset, \
                   base_asset, \
                   quote_asset, \
                   'sell'
        # returns: (pairing, base asset symbol, quote asset symbol, side)

    # _split_a_pairing() takes a pairing and returns two separate asset symbols
    # if ret_valid_pairing is False it returns two valid symbols in the order passed in,
    # regardless of if there's a valid pairing
    # if ret_valid_pairing is True it will flip the symbols around to make a valid pairing if necessary
    def _split_a_pairing(self, pairing_to_split: str, ret_valid_pairing: bool = False) -> Tuple[str, str] or str:
        quote_asset, base_asset = self._pair_splitter(pairing_to_split)
        input_check_qa = self._input_check(symbol=quote_asset)
        input_check_ba = self._input_check(symbol=base_asset)
        if input_check_qa is not True:
            return input_check_qa
        elif input_check_ba is not True:
            return input_check_ba
        if ret_valid_pairing is False:
            return quote_asset, base_asset

        qa_plus_ba = quote_asset + base_asset
        ba_plus_qa = base_asset + quote_asset
        input_check_p1 = self._input_check(pairing=qa_plus_ba)
        input_check_p2 = self._input_check(pairing=ba_plus_qa)

        if input_check_p1 is True:  # this has to have 'is True,' a tuple is returned otherwise, tuple isn't false
            return quote_asset, base_asset
        elif input_check_p2 is True:
            return base_asset, quote_asset
        else:
            if input_check_p1 is not True:
                return input_check_p1
            if input_check_p2 is not True:
                return input_check_p2

    # does the actual splitting for _split_a_pairing()
    def _pair_splitter(self, pairing_to_split: str) -> Tuple[str, str]:
        # input will be checked in _split_a_pairing(), so no need for that here
        asset1 = ''
        asset2 = ''
        for symbol in self._get_asset_symbols('base'):
            if symbol in pairing_to_split:
                asset1 = symbol
                break
        for symbol in self._get_asset_symbols('base'):
            if symbol in pairing_to_split and symbol not in asset1:
                asset2 = pairing_to_split.replace(asset1, '')
                break
        if asset2 + asset1 == pairing_to_split:
            return asset2, asset1
        return asset1, asset2

    # USDC is the asset this program has to use every single transaction, so if a pairing with it
    # doesn't exist this function returns a 'pairing path' to USDC so I can pay the tax man
    def _get_pairing_path_to_usdc(self, symbol: str) -> Tuple[str] or Tuple[str, str]:
        symbol = symbol.upper()
        pairings_with_asset = []
        input_check = self._input_check(None, None, None, symbol, None)
        if input_check is not True:
            return input_check
        else:
            for pairing in self.get_pairing_list():  # grabs all possible pairings for the asset
                if symbol in pairing:
                    pairings_with_asset.append(pairing)
            pairing_path = []
            for pairing in pairings_with_asset:  # cycles through all possible pairings
                if 'USDC' in pairing:   # if there's a direct pairing with USDC, then great!
                    pairing_path.append(pairing)
                    return tuple(pairing_path)
            for pairing in pairings_with_asset:  # if not, add the asset's BTC pairing to a list, then add BTCUSDC to it
                if 'BTC' in pairing:
                    pairing_path.append(pairing)
                    pairing_path.append('BTCUSDC')
                    return tuple(pairing_path)
        # this only works because every single asset on Binance has a BTC pairing. if that changes later
        # then this logic has to change
        # TODO rethinking this to work around that sounds like a fun challenge for later

    # formatting for these parameters (like pairing.upper() or side.lower()
    # in the following functions should done in the functions that send them
    # since they use those arguments too

    # these functions check user input in the cli, and tells you if you constructed something wrong in a gui

    def _confirm_pairing_valid(self, pairing: str) -> bool:
        for item in self.get_pairing_list():
            if pairing == item:
                return True
        return False

    def _confirm_symbol_valid(self, symbol: str) -> bool:
        for item in self._get_asset_symbols('base'):
            if symbol == item:
                return True
        return False

    @staticmethod
    def _confirm_valid_side(side: str) -> bool:
        if side == 'buy' or side == 'bid' or side == 'sell' or side == 'ask':
            return True
        return False

    @staticmethod
    def _confirm_nonzero_qty(qty: Decimal) -> bool:
        if qty > decimal_zero:
            return True
        return False

    @staticmethod
    def _confirm_valid_pairing_side(pairing_side: str) -> bool:
        if pairing_side == 'quote' or pairing_side == 'base':
            return True
        return False

    # makes sure that all the parameters of a function being called are valid
    def _input_check(self, pairing: str = None, side: str = None,
                     qty: Decimal = None, symbol: str = None,
                     pairing_side: str = None) -> bool or tuple:
        error_list = []
        if pairing is not None:
            if not self._confirm_pairing_valid(pairing):
                error_list.append('invalidPairing')
        if side is not None:
            if not self._confirm_valid_side(side):
                error_list.append('invalidSide')
        if qty is not None:
            if not self._confirm_nonzero_qty(qty):
                error_list.append('invalidDecimal')
        if symbol is not None:
            if not self._confirm_symbol_valid(symbol):
                error_list.append('invalidSymbol')
        if pairing_side is not None:
            if not self._confirm_valid_pairing_side(pairing_side):
                error_list.append('invalidPairingSide')
        if not error_list:
            return True
        return tuple(error_list)

    #   Examples:
    #       pairing: 'USDCBTC'
    #       side: 'buy' or 'sell'
    #       qty: decimal.Decimal('4.513')
    #       symbol: 'ETH'
    #       pairing_side: 'quote' or 'base'

    # I need this to determine the lot size in execute_trade()
    def _get_pairing_lot_size(self, pairing: str) -> str:
        symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
        symbols_json = json.loads(symbols_string.text)
        for item in symbols_json['symbols']:
            if item['symbol'] == pairing:
                for filter_dict in item['filters']:
                    if filter_dict['filterType'] == 'LOT_SIZE':
                        return str(filter_dict['minQty'])[1:]
