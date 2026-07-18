class OrderStore:
    def __init__(self):
        self.orders = {}
        self.audit = []

    def add(self, order):
        self.orders[order.order_id] = order
