from db import engine, Base
from model import User, SessionToken
# Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
print("$$GOOD$$")
