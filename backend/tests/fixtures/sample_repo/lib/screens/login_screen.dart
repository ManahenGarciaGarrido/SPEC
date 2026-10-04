import 'package:flutter/material.dart';

import '../auth/auth_repository.dart';

/// Pantalla de inicio de sesión: pide correo y contraseña.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.auth});

  final AuthRepository auth;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  String? _error;

  Future<void> _submit() async {
    try {
      await widget.auth.login(_email.text, _password.text);
      if (mounted) Navigator.of(context).pushReplacementNamed('/home');
    } on ArgumentError catch (e) {
      setState(() => _error = e.message.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          TextField(controller: _email, decoration: const InputDecoration(labelText: 'Correo')),
          TextField(controller: _password, obscureText: true),
          if (_error != null) Text(_error!, style: const TextStyle(color: Colors.red)),
          ElevatedButton(onPressed: _submit, child: const Text('Entrar')),
        ],
      ),
    );
  }
}
