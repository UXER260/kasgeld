import copy
import datetime
import json
import os
import sys

import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel

# todo: split transactions date and time into separate values: year, month, day and hour, minute

app = FastAPI()

with open("config.json", "r") as f:
    config = json.load(f)

if not os.path.exists(config["accounts_path"]):
    with open(config["accounts_path"], "w") as f:  # create file
        f.write("{}")
elif os.path.isdir(config["accounts_path"]):
    raise IOError(f"Item `{config['accounts_path']}` moet een json file zijn, geen folder.")


class AccountField(BaseModel):
    name: str
    money: float
    transactions: list[dict]
    savings: list[dict]
    last_salary_date: list[int]
    # data_of_birth: list[int]


class SavingsField(BaseModel):
    name: str
    cost: float
    description: str


class TransactionField(BaseModel):
    amount_to_set: float
    title: str
    description: str
    date: str = ""
    time: str = ""


class TransactionJsonField(BaseModel):
    title: str
    amount: float  # NOT saldo after the transaction. but the amount that got added or subtracted
    # (x or -x, 1 or -1 depending on whether the user earned or lost money)
    description: str
    saldo_after_transaction: float
    date: str
    time: str


class TimeAndDate(BaseModel):
    second: int
    minute: int
    hour: int
    day: int
    month: int  # 1-12
    year: int
    today: str  # y-m-d
    time: str  # h:m:s


month_map = {
    1: "januari",
    2: "februari",
    3: "maart",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "augustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "december",
}


@app.middleware("http")
async def middleware(request: Request, call_next):
    account_data = get_all_account_data()
    t_and_d = time_and_date()
    current_year, current_month = t_and_d.year, t_and_d.month
    for account in account_data.values():
        last_rec_year, last_rec_month = account.last_salary_date[0], account.last_salary_date[1]
        money_months = (current_year * 12 + current_month) - (last_rec_year * 12 + last_rec_month)
        if money_months > 0:
            for month in range(money_months):
                converted_month = (last_rec_month + month) % 12 + 1
                if converted_month in config["month_salary_blacklist"]:  # je krijgt 10 × kasgeld (in plaats van 12)
                    continue
                # # kasgeld_datum = f"{}"
                month_name = month_map[converted_month]
                year = int(last_rec_year + month / 12)
                transaction_details = TransactionField(
                    amount_to_set=account.money + config["salary_amount"],
                    title=f"Kasgeld {month_name}",
                    description=f"Kasgeld voor {month_name} {year}",
                    date=t_and_d.today,
                    time=t_and_d.time
                )
                set_saldo(account=account, transaction_details=transaction_details)
                account.last_salary_date = [current_year, current_month]

    response = await call_next(request)

    return response


@app.get("/time_and_date")
def time_and_date():
    d = datetime.datetime.now()
    return TimeAndDate(
        **{"second": d.second, "minute": d.minute, "hour": d.hour, "day": d.day, "month": d.month, "year": d.year,
           "today": str(datetime.date.today()), "time": f"{d.hour}:{d.minute}:{d.second}"})


@app.get("/get_all_account_data")
def get_all_account_data():
    with open(config["accounts_path"]) as file:
        accounts_file = json.load(file)
    new_accounts_file = {}
    for name, data in accounts_file.items():
        new_accounts_file[name] = AccountField(**data)
    return new_accounts_file


@app.get("/get_dict_account_data")
def get_dict_account_file(account_data):
    new_accounts_file = {}
    for name, data in account_data.items():
        new_accounts_file[name] = data.model_dump()
    return new_accounts_file


@app.get("")
def get_account_data(account_name):
    with open(config["accounts_path"]) as file:
        accounts_file = json.load(file)
    account_data = accounts_file.get(account_name)
    # if account_data is None:
    #     raise exceptions.HTTPException(status.HTTP_404_NOT_FOUND, f"account with name {account_name} was not found")
    return account_data


@app.delete("/delete_account")
def delete_account(account: AccountField):
    account_data = get_all_account_data()
    try:
        del account_data[account.name]
        apply_changes(account_data=account_data)
        return True  # todo
    except KeyError:
        return False  # todo


@app.put("/rename_account")
def rename_account(account_name: str, new_name: str):
    if not check_account_exists(new_name):
        account_data = get_all_account_data()
        account_data[account_name].name = new_name
        account_data[new_name] = account_data.pop(account_name)
        apply_changes(account_data=account_data)
    else:
        return "ExistsError"


@app.get("/check_account_exists")
def check_account_exists(account_name: str):
    account_data = get_all_account_data()
    return account_name in account_data.keys()


@app.post("/add_account_to_file")
def add_account_to_file(account_info: AccountField):  # obvious
    name, saldo, transactions, savings = \
        account_info.name, account_info.money, account_info.transactions, account_info.savings
    if savings is None:
        savings = []
    if transactions is None:
        transactions = []

    elif check_account_exists(name) is True:
        print(f"`{name}` account already exists")
        return "ExistsError"

    account_data = get_all_account_data()
    t_and_d = time_and_date()
    account_data[name] = AccountField(
        **{"name": name, "money": saldo, "transactions": transactions, "savings": savings,
           "last_salary_date": [t_and_d.year, t_and_d.month]})
    apply_changes(account_data=account_data)
    return account_data[name]


@app.get("/get_account_name_list")
def get_account_name_list() -> list:  # obvious
    accounts_data = get_all_account_data()
    return [account.name for account in accounts_data.values()]


@app.put("/apply_changes")
def apply_changes(account_data) -> None:  # writes changes to "accounts" file
    with open(config["accounts_path"], "w") as file:
        json.dump(get_dict_account_file(account_data=account_data), file, indent=2)


@app.put("/set_saldo")
def set_saldo(account: AccountField, transaction_details: TransactionField):
    account_data = get_all_account_data()
    if not check_account_exists(account.name):
        print("Account does not exist")
        return False  # todo
    account_data[account.name].transactions.append(
        generate_transaction(current_money=account.money,
                             transaction_details=TransactionField(
                                 amount_to_set=transaction_details.amount_to_set,
                                 title=transaction_details.title,
                                 description=transaction_details.description)))
    account_data[account.name].money = transaction_details.amount_to_set

    account.money = account_data[account.name].money
    account.transactions = account_data[account.name].transactions

    apply_changes(account_data=account_data)  # writes to the actual accounts file.
    return account


@app.post("/add_saving")
def add_saving(account: AccountField, saving_info: SavingsField) -> None:  # obvious
    account_data = get_all_account_data()
    account_data[account.name].savings.append(generate_saving(saving_info=saving_info))
    account.savings = account_data[account.name].savings

    apply_changes(account_data=account_data)  # writes to the actual accounts file.


@app.get("/get_transaction_header_list")
def get_transaction_header_list(account_name: str):
    if not check_account_exists(account_name):
        return False  # todo
    account_data = get_all_account_data()
    transaction_header_list = []
    for transaction in account_data[account_name].transactions:
        header = generate_transaction_header(
            TransactionJsonField(**transaction)
        )
        transaction_header_list.append(header)

    return reverse(transaction_header_list)


@app.get("/generate_saving")
def generate_saving(saving_info: SavingsField) -> dict:  # convert to appropriate format before adding saving
    name, cost, description = saving_info.name, saving_info.cost, saving_info.description

    return {name: {"cost": cost, "description": description}}


@app.post("/generate_transaction")
def generate_transaction(
        current_money: float, transaction_details: TransactionField):  # for fancy transaction text

    # amount_to_set, title, description, date, time = \
    #     transaction_details.amount_to_set, \
    #     transaction_details.title, \
    #     transaction_details.description, \
    #     transaction_details.date, \
    #     transaction_details.time
    if type(transaction_details.amount_to_set) is not float:
        return "InvalidSaldoError"

    amount = transaction_details.amount_to_set - current_money

    if not transaction_details.date:
        transaction_details.date = str(datetime.date.today())
    if not transaction_details.time:
        d = time_and_date()
        transaction_details.time = f"{d.hour}:{d.minute}:{d.second}"

    return {"title": transaction_details.title, "amount": amount, "description": transaction_details.description,
            "saldo_after_transaction": transaction_details.amount_to_set, "date": transaction_details.date,
            "time": transaction_details.time}


def generate_transaction_header(transaction_details: TransactionJsonField) -> str:
    amount, title, date = transaction_details.amount, \
        transaction_details.title, \
        transaction_details.date
    return f"€{amount} [{title}] | {date}"


# # # # # # # # # # # # # # # # # # # # # # # # # # #

# todo: add to Camillib
def filter_list(search, seq, conv_lower=True) -> list:
    if conv_lower:
        return [item for item in seq if search.lower() in item.lower()]
    else:
        return [item for item in seq if search in item]


def reverse(seq):  # todo: replace with build in function
    t = copy.deepcopy(seq)
    t.reverse()
    return t


def on_exit(message=None) -> None:
    if message is None:
        sys.exit(0)
    else:
        sys.exit(str(message))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config["port"])
