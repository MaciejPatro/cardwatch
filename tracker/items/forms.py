from django import forms
from .models import Item

class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = "__all__"
        widgets = {
            "buy_date": forms.DateInput(attrs={"type": "date"}),
            "sell_date": forms.DateInput(attrs={"type": "date"}),
        }
