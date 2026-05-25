FROM node:20-alpine

WORKDIR /app

COPY package.json .
RUN npm install --strict-ssl=false

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
