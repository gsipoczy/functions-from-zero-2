import src.util as ut
import lib.pdf as pdfutil

def add(x,y):
    return x + y

def multiply(x,y):
    return ut.multiply(x,y)

text = pdfutil.pdf_to_text("sample.pdf")
print(text)

