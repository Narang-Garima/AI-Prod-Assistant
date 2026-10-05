import uvicorn


def main():
    uvicorn.run("prod_assistant.router.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
