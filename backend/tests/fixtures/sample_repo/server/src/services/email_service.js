const nodemailer = require("nodemailer");

// Sends the welcome e-mail after a user signs up.
async function sendWelcomeEmail(user) {
  const transport = nodemailer.createTransport({ host: "localhost", port: 1025 });
  await transport.sendMail({
    to: user.email,
    subject: "Bienvenido",
    text: `Hola ${user.displayName}, gracias por registrarte.`,
  });
}

module.exports = { sendWelcomeEmail };
