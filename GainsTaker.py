# this is my first actually useful program. my gratitude to nick winn, pyslackers chat room (EdKeyes and dd82),
# /r/learnpython, learnprogramming.academy, real python, and others for helping me get this far!

import requests
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
    # returns a formatted super().get_tax_due()
    @staticmethod
    def get_tax_due(spend_total_usd: Decimal, cost_basis_usd: Decimal = None, term: str = 'short') \
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
    def format_a_decimal(dec: Decimal, lot_size: str, round_direction: str = 'ROUND_DOWN') -> Decimal:
        lot_size = Decimal(lot_size)
        return Decimal(dec.quantize(Decimal(lot_size), rounding=round_direction))

    # Binance gets its own get_tax_due() because it only works with up to 6 decimal places, so it needs
    # to be formatted as such
    def get_tax_due(self, spend_total_usd: Decimal, cost_basis_usd: Decimal = None, term: str = 'short') \
            -> Decimal or str:
        return self.format_a_decimal(super().get_tax_due(spend_total_usd, cost_basis_usd, term),
                                     lot_size='.01', round_direction='ROUND_UP')
        # LOT_SIZE of .01 here because although though usdc supports more decimal places,
        # this will be getting rounded up for the tax man anyway

    # The following functions work with information from Binance using the following formats:

    #   Examples:
    #       pairing: 'ETHUSDC'
    #       side: 'buy' or 'sell'
    #       qty: decimal.Decimal('4.513')
    #       symbol: 'ETH'
    #       pairing_side: 'quote' or 'base'

    # with 'ETHUSDC' as 'pairing' in get_pairing_converted_value():
    # side = 'buy' to convert USDC value to ETH value
    # side = 'sell' to convert ETH value to USDC value
    # API seems to only return the order books about 1,000,000 USD deep
    # TODO make this function estimate spends for crazy large amounts quickly
    def get_pairing_converted_value(self, pairing: str, spend_amount: Decimal, side: str = 'buy') -> tuple:
        side = side.lower()
        pairing = pairing.upper()
        book = None
        input_check = self._input_check(pairing=pairing, side=side, qty=spend_amount)
        if input_check is not True:
            return input_check
        if side == 'buy':
            book = 'asks'
        if side == 'sell':
            book = 'bids'
        api_url = self.API_URL + "v1/depth"
        orders = requests.get(api_url, params={'symbol': pairing, 'limit': 1000})
        if orders.status_code >= 400:
            return orders.status_code
        running_cost = decimal_zero
        qty_counter = decimal_zero
        quote, base = self.split_a_pairing(pairing)
        lot_size = self._get_pairing_lot_size(pairing=pairing, side=side)
        for order in orders.json()[book]:
            order_0, order_1 = Decimal(order[0]), Decimal(order[1])
            cost = order_0 * order_1
            if side == 'buy':
                if cost + running_cost >= spend_amount:
                    left_to_spend = spend_amount - running_cost
                    remaining_qty_to_buy = left_to_spend/order_0
                    total_bought = qty_counter + remaining_qty_to_buy
                    total_bought = self.format_a_decimal(dec=total_bought, lot_size=lot_size)
                    return total_bought, quote
                running_cost += cost
                qty_counter += order_1
            if side == 'sell':
                if order_1 + running_cost >= spend_amount:
                    left_to_spend = spend_amount - running_cost
                    remaining_qty_to_buy = order_0 * left_to_spend
                    total_bought = qty_counter + remaining_qty_to_buy
                    total_bought = self.format_a_decimal(dec=total_bought, lot_size=lot_size)
                    return total_bought, base
                running_cost += order_1
                qty_counter += cost

    # get_price_usdc() is like a get_pairing_price(), except it is exclusively USDC, and if a pairing
    # doesn't exist, it uses BTC as a go between and returns the appropriate values as though it did
    # so now we can get a USDC price for every asset available on Binance
    # if symbol is 'XMR': 'buy' means send usdc value return xmr value; 'sell' means send xmr value return usdc value
    def get_price_usdc(self, symbol: str, qty: Decimal, side: str = 'buy') -> tuple:
        symbol = symbol.upper()
        side = side.lower()
        input_check = self._input_check(None, side, qty, symbol)
        if input_check is not True:
            return input_check
        path_to_usdc = self._get_pairing_path_to_usdc(symbol=symbol)
        if len(path_to_usdc) == 1:
            return self.get_pairing_converted_value(pairing=path_to_usdc[0], spend_amount=qty, side=side)
        if side == 'sell':
            btc_qty = self.get_pairing_converted_value(pairing=path_to_usdc[0], spend_amount=qty, side='sell')
            return self.get_pairing_converted_value(pairing=path_to_usdc[1], spend_amount=btc_qty[0], side='sell')
        btc_qty = self.get_pairing_converted_value(pairing=path_to_usdc[1], spend_amount=qty, side='buy')
        return self.get_pairing_converted_value(pairing=path_to_usdc[0], spend_amount=btc_qty[0], side='buy')

    # get_balances() takes any number of symbols passed in as parameters, and yields balances in tuples
    # if all_symbols is True, it yields all balances
    # ex: get_balances('ETH', 'XMR', 'USDC', 'BNB')
    # zero_balances does nothing if all_symbols isn't True
    # sending symbols as *argv parameter with all_symbols turned on and zero balances off results
    # in specified zero balances being displayed along with all nonzero balances
    def get_balances(self, *args, all_symbols: bool = False, show_zero_balances: bool = False):
        query_string = 'timestamp=' + str(int(time.time()) * 1000)
        sig = self.get_signature(query_string)
        balances = requests.get(self.API_URL + 'v3/account?' +
                                query_string + '&signature=' + sig, headers=self.headers)
        if balances.status_code >= 400:
            return balances.status_code
        if all_symbols:
            for asset_dict in balances.json()['balances']:
                return_dec = self.format_a_decimal(Decimal(asset_dict['free']), lot_size='.000001')
                if not show_zero_balances and return_dec != decimal_zero:
                    yield return_dec, asset_dict['asset']
                elif show_zero_balances:
                    yield return_dec, asset_dict['asset']
        for symbol in args:
            symbol = symbol.upper()
            input_check = self._input_check(None, None, None, symbol)
            if input_check is not True:
                return input_check
            else:
                for asset_dict in balances.json()['balances']:
                    if asset_dict['asset'] == symbol:
                        yield self.format_a_decimal(Decimal(asset_dict['free']), lot_size='.000001'), symbol

    # make the tax trade(s) before the main trade's function gets called
    # figures out the necessary trades to convert the given asset to the USDC amount given
    # then executes those trades using execute_trade()
    def execute_tax_trade(self, asset_being_sold: str,  tax_due_usd: Decimal) -> tuple:
        path_to_usdc = self._get_pairing_path_to_usdc(symbol=asset_being_sold)
        tax_due_as_sym = self.get_price_usdc(symbol=asset_being_sold, qty=tax_due_usd, side='buy')[0]
        if len(path_to_usdc) == 1:
            symusdc = path_to_usdc[0]
            return self.execute_trade(pairing=symusdc, qty=tax_due_as_sym, side='sell')
        symbtc = path_to_usdc[0]
        btcusdc = path_to_usdc[1]
        tax_to_btc = self.execute_trade(pairing=symbtc, qty=tax_due_as_sym, side='sell')[0]
        return self.execute_trade(pairing=btcusdc, qty=tax_to_btc, side='sell')
        # format_a_decimal() isn't necessary in either of these conditionals because execute_trade() calls it
        # before returning
    #     TODO this is untested, spun it while running a different OS where I don't have my API keys
    #     TODO add commit description to record on ubuntu

    # execute_trade() actually executes the trade
    def execute_trade(self, pairing: str, qty: Decimal, side: str = 'buy') -> tuple:
        pairing = pairing.upper()
        side = side.lower()  # make it lower because that's how i made my _input_check() want it
        input_check = self._input_check(pairing=pairing, side=side, qty=qty)
        if input_check is not True:
            return input_check
        side = side.upper()  # making it upper now to format for insertion into the query string
        lot_size = self._get_pairing_lot_size(pairing, side)
        qty = self.format_a_decimal(qty, lot_size=lot_size)
        qty = str(qty)

        # split the pairing, determine the balance of the asset being gained,
        # store the balance compare with new balance after the order is executed
        # so it can be returned, I don't see a way to do this through Binance API
        # an alternative approach might've been to use newOrderRespType=FULL below, and
        # derive it from the 'fills' values, but this seemed easier
        quote_asset, base_asset = self.split_a_pairing(pairing)
        if side == 'BUY':
            asset_to_use = quote_asset
        else:
            asset_to_use = base_asset
        bal_before_acquiring = tuple(self.get_balances(asset_to_use))

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
        if order.status_code >= 400:
            return order.status_code

        # parse and return results
        result = order.json()
        bal_after_acquiring = tuple(self.get_balances(asset_to_use))  # returns a Decimal
        amt_of_asset_acquired = Decimal(bal_after_acquiring[0][0]) - Decimal(bal_before_acquiring[0][0])
        # these are only casted as Decimal to humor my IDE ^
        amt_of_asset_acquired = self.format_a_decimal(amt_of_asset_acquired, lot_size=lot_size)
        return amt_of_asset_acquired, asset_to_use, result
        # returns a tuple: (Decimal containing amount acquired, asset acquired, binance's response to POST)

    # get_pairing_list() returns a tuple of possible pairings available on binance
    # oddly, USDCBTC returns as a valid pairing, when it is not, resulting in changes to several of
    # this class' functions
    def get_pairing_list(self) -> tuple:
        symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
        symbols_json = symbols_string.json()
        return_list = []
        for item in symbols_json['symbols']:
            return_list.append(item['symbol'])
        return_list.remove('USDCBTC')
        return_list.remove('USDCBNB')
        return_list.remove('USDCUSDT')
        return_list.remove('USDCTUSD')
        return_list.remove('USDCPAX')
        return tuple(return_list)

    # _get_asset_symbols() returns a tuple of asset symbols
    # pairing_side:'quote' produces a list of symbols that are the first part of a pairing
    # pairing_side:'base' produces a list of symbols that are in the second part (all of them,
    # in one pairing or another. use 'base to generate a list of every asset binance handles
    def _get_asset_symbols(self, pairing_side: str = 'base') -> tuple:
        pairing_side = pairing_side.lower()
        input_check = self._input_check(None, None, None, None, pairing_side)
        if input_check is not True:
            return input_check
        symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
        symbols_json = symbols_string.json()
        assets_set = set()
        if pairing_side == 'base':
            assets_set.add('USDT')
            assets_set.add('USDC')
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
    def split_a_pairing(self, pairing_to_split: str, ret_valid_pairing: bool = False) -> Tuple[str, str] or str:
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
        while True:
            for symbol in self._get_asset_symbols():
                if symbol == pairing_to_split[0:len(symbol)]:
                    quote = symbol
                    base = pairing_to_split[len(symbol):]
                    base_check = self._input_check(symbol=base)
                    if base_check is True:
                        return quote, base

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
        for item in self._get_asset_symbols():
            if symbol == item:
                return True
        return False

    @staticmethod
    def _confirm_valid_side(side: str) -> bool:
        if side == 'buy' or side == 'sell':
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
            if not self._confirm_pairing_valid(pairing) or pairing == 'USDCBTC' \
                    or pairing == 'USDCBNB' or pairing == 'USDCUSDT' or pairing == 'USDCTUSD' \
                    or pairing == 'USDCPAX':
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
    #       pairing: 'ETHUSDC'
    #       side: 'buy' or 'sell'
    #       qty: decimal.Decimal('4.513')
    #       symbol: 'ETH'
    #       pairing_side: 'quote' or 'base'

    # I need these to determine the lot size in execute_trade()
    def _get_pairing_lot_size(self, pairing: str, side: str) -> str:
        # fetches this pairing's lot size
        this_lot = self._get_lot_size(pairing)
        if side == 'buy':
            return this_lot
        # below corrects a sell side issue with IOTA, but will apply to other cryptos with very large supply
        # fetches an alternate size
        alt_pairing = self._get_alt_lot_pairing(pairing)
        alt_lot = self._get_lot_size(alt_pairing)
        # goes with whichever's bigger if side sent is 'sell'
        if len(alt_lot) > len(this_lot):
            return alt_lot
        return this_lot

    def _get_lot_size(self, pairing: str):
        symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
        if symbols_string.status_code >= 400:
            return symbols_string.status_code
        symbols_json = symbols_string.json()
        for item in symbols_json['symbols']:
            if item['symbol'] == pairing:
                for filter_dict in item['filters']:
                    if filter_dict['filterType'] == 'LOT_SIZE':
                        return str(filter_dict['minQty']).rstrip('0')

    # if there's any pairings where the sent base can be used as a quote, _pairing_with_given_base_as_quote()
    # returns it, otherwise it returns None
    # binance appears to default to the larger lot size for a symbol in a pair, so I have to compare two pairings
    # to get an appropriate lot size
    def _get_alt_lot_pairing(self, pairing: str) -> str:
        quote, base = self.split_a_pairing(pairing)
        if base == 'USDC':
            return 'USDCBTC'
        if base == 'ETH':
            return 'ETHBTC'
        if base == 'TUSD':
            return 'TUSDBTC'
        if base == 'USDS':
            return 'USDSPAX'
        if base == 'PAX':
            return 'PAXBTC'
        if base == 'TRX':
            return 'TRXBTC'
        if base == 'BNB':
            return 'BNBBTC'
        if base == 'BTC':
            return 'BTCUSDT'
        if base == 'XRP':
            return 'XRPBTC'
        if base == 'USDT':
            return pairing
