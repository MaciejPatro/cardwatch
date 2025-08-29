from django.db import models

CURRENCIES = [
    ("CHF", "Swiss Franc"),
    ("EUR", "Euro"),
    ("USD", "US Dollar"),
    ("PLN", "Polish Zloty"),
]

class Item(models.Model):
    name = models.CharField(max_length=128)
    buy_date = models.DateField()
    link = models.URLField(blank=True)
    graded = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCIES)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    sell_date = models.DateField(blank=True, null=True)
    image = models.ImageField(upload_to="item_images/", blank=True, null=True)


    def __str__(self):
        return self.name