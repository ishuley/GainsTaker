import requests
import json
import time
import hmac
import hashlib
import decimal
from decimal import Decimal
from typing import Iterator, Tuple

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
    # returns a formatted super().get_class_due()
    @staticmethod
    def get_tax_due(spend_total_usd: Decimal, cost_basis_usd: Decimal = None, term: str = 'short') -> Decimal or str:
        # god bless America
        term = term.lower()
        if term != 'short' and term != 'long':
            return 'invalidTerm'
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
    def format_a_decimal(dec: Decimal, round_direction: str = 'ROUND_DOWN') -> Decimal:
        return Decimal(dec.quantize(Decimal('.000001'), rounding=round_direction))

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
    def get_pairing_price(self, pairing: str, side: str = 'buy', qty=decimal_zero) -> tuple:
        side = side.lower()
        pairing = pairing.upper()
        flip_symbols = False
        input_check = self._input_check(pairing, side, qty)
        if input_check is not True:  # _input_check() either returns True, or a tuple containing applicable error ids
            return input_check
        else:
            if pairing == 'USDCBTC':  # for some reason USDCBTC returns as a valid pairing, but the market is BTCUSDC
                pairing = 'BTCUSDC'
                flip_symbols = True
                if side == 'sell':
                    side = 'buy'
                else:
                    side = 'sell'
            if side == 'buy':  # determines which side of the orderbook to use
                book = 'asks'
            else:
                book = 'bids'
            api_url = self.API_URL + "v1/depth"
            orders = requests.get(api_url, params={'symbol': pairing, 'limit': 1000})
            orders_json = json.loads(orders.text)
            order_book = orders_json[book]  # so now we have an iterable list of orders to estimate a price with
            qty_counter = decimal_zero
            price = decimal_zero
            buy_asset = None
            buy_asset_qty = None
            symbol1, symbol2 = self._split_a_pairing(pairing)
            for order in order_book:  # figures out how much we'll have to pay using orderbook information
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
                if flip_symbols:  # if flip symbols is true, USDCBTC got sent instead of BTCUSDC
                    buy_asset = symbol2
                else:
                    buy_asset = symbol1
            elif book == 'bids':
                buy_asset_qty = qty * price
                if flip_symbols:
                    buy_asset = symbol1
                else:
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
                return self.get_pairing_price('BTCUSDC', other_side, qty)
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

    def pay_the_man(self, tax_due_usd: Decimal, asset_being_sold: str):
        pass

    def execute_trade(self, pairing: str, side: str, qty: Decimal):
        pass

    # get_pairing_list() generates a list of pairings available on binance
    def get_pairing_list(self) -> Iterator[str]:
        symbols_string = requests.get(self.API_URL + 'v1/exchangeInfo')
        symbols_json = json.loads(symbols_string.text)
        for item in symbols_json['symbols']:
            yield item['symbol']

    # _get_asset_symbols() generates a list of asset symbols
    # 'quote' produces a list of symbols that are the first part of a pairing
    # 'base' produces a list of symbols that are in the second part
    # use 'base' to produce a list of every asset binance handles
    def _get_asset_symbols(self, pairing_side: str) -> Iterator[str] or tuple:
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
            for item in assets_set:
                yield item

    # get_valid_pairing() returns a tuple for a valid pairing if one exists for the given assets
    # if the asset sides (quote, base) had to be switched
    # (ex: ARDRETH only exists but you send ETH as quote asset and ARDR as base), then it returns sell instead of buy
    def get_valid_pairing(self, quote_asset: str, base_asset: str) -> Tuple[str, str, str, str] or tuple:
        base_asset, _quote_asset = base_asset.upper(), quote_asset.upper()
        input_check_q = self._input_check(None, None, None, _quote_asset, None)
        input_check_b = self._input_check(None, None, None, base_asset, None)
        input_check_p = self._confirm_pairing_valid(base_asset + _quote_asset)
        if input_check_b is not True:
            return input_check_b
        if input_check_q is not True:
            return input_check_q
        if input_check_p is not True:
            return input_check_p
        if self._confirm_pairing_valid(_quote_asset + base_asset):
            return _quote_asset + base_asset, \
                   _quote_asset, \
                   base_asset, \
                   'buy'
        elif input_check_p:
            return base_asset + _quote_asset, \
                   base_asset, \
                   _quote_asset, \
                   'sell'
        # returns: (pairing, base asset symbol, quote asset symbol, side)

    # _split_a_pairing() takes a pairing and returns two separate asset symbols
    # switches them for you similar to get_valid_pairing() if necessary
    def _split_a_pairing(self, pairing_to_split: str) -> Tuple[str, str] or str:
        quote_asset = None
        base_asset = None
        for symbol in self._get_asset_symbols('quote'):
            if symbol in pairing_to_split:
                quote_asset = symbol
                break
        for symbol in self._get_asset_symbols('base'):
            if symbol in pairing_to_split and symbol not in quote_asset:
                base_asset = symbol
                break
        input_check_qa = self._input_check(None, None, None, quote_asset)
        input_check_ba = self._input_check(None, None, None, base_asset)
        qa_plus_ba = quote_asset + base_asset
        ba_plus_qa = base_asset + quote_asset
        input_check_p1 = self._input_check(qa_plus_ba)
        input_check_p2 = self._input_check(ba_plus_qa)
        # error checking below this line
        if input_check_qa is not True:
            return input_check_qa
        if input_check_ba is not True:
            return input_check_ba
        # checks each symbol as base and quote, and returns the tuple in correct order
        if self._input_check(qa_plus_ba):
            return quote_asset, base_asset
        elif self._input_check(ba_plus_qa):
            return base_asset, quote_asset
        # error checking below this line
        else:  # this only happens if one of the pairings is the problem
            if input_check_p1 is not True:
                return input_check_p1
            if input_check_p2 is not True:
                return input_check_p2

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
    # in the following functions should done the functions that send them
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
