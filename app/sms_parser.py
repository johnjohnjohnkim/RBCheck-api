import re



def parseTransaction(text):
    '''
    Cheeky function finding where the embedded message within attributedBody starts and ends.
    Much easier to do this than parse through NSString (yuck)

    @returns string text of the transaction
    '''
    startPos = text.find("RBC: ")
    if startPos == -1:
        startPos = text.find("DEPOSIT")
    if startPos == -1:
        startPos = text.find("AVAIL CREDIT")
        return "bw" #For Balance Warning
    endPos = text.find("HELP-TXT HELP")

    return text[startPos:endPos]


def transactionAnalysis(text):
    '''
    
    '''
    transactionType = ""
    if text == "bw":
        transactionType = "Balance Warning!"
    amount = re.search(r'\$([\d.,]*\d)', text)
    amount = amount.group(1) if amount else None


    place = re.search(r'AT (.+?)(?:\. STOP-TXT| STOP-TXT)', text)
    place = place.group(1) if place else ""

    if "DEPOSIT" in text:
        transactionType = "Deposit"
    elif "WITHDRAWAL" in text:
        transactionType = "Withdrawal"
    elif "PURCHASE" in text:
        transactionType = "CC Purchase"
    elif "PAYMENT OF" in text:
        transactionType = "Credit Card Payment"
    elif "CREDITED FOR" in text:
        transactionType = "Credit Refund"
    return amount, place, transactionType