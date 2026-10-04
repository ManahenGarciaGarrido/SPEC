import '../models/user.dart';
import '../services/api_client.dart';

/// Handles authentication against the backend API.
class AuthRepository {
  AuthRepository(this._client);

  final ApiClient _client;
  User? _currentUser;

  User? get currentUser => _currentUser;

  /// Logs the user in and keeps the session token in memory.
  Future<User> login(String email, String password) async {
    if (!validateEmail(email)) {
      // El correo debe tener un formato válido antes de llamar al servidor.
      throw ArgumentError('Email no válido: $email');
    }
    final response = await _client.post('/auth/login', {
      'email': email,
      'password': password,
    });
    _currentUser = User.fromJson(response['user'] as Map<String, dynamic>);
    return _currentUser!;
  }

  /// Checks the e-mail format with a simple regular expression.
  bool validateEmail(String email) {
    final pattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');
    return pattern.hasMatch(email);
  }

  Future<void> logout() async {
    await _client.post('/auth/logout', {});
    _currentUser = null;
  }
}
