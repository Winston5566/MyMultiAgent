
def calculate(a: float, b: float, operation: str):
    """执行加减乘除运算"""

    if operation == "add":
        return a + b

    elif operation == "subtract":
        return a - b

    elif operation == "multiply":
        return a * b

    elif operation == "divide":
        if b == 0:
            return "错误：除数不能为0"
        return a / b

    else:
        return "不支持的运算"
